"""Discovery regression tests with real HTTP client types and minimal HA stubs.

The stubs cover only the form boundary, not a running Home Assistant instance.
"""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / 'custom_components' / 'homeassistant_checkmk'


class FlowBase:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()


def load_flow():
    ha = ModuleType('homeassistant')
    ha.config_entries = SimpleNamespace(ConfigFlow=FlowBase, OptionsFlow=FlowBase)
    const = ModuleType('homeassistant.const')
    const.CONF_HOST, const.CONF_USERNAME, const.CONF_PASSWORD = 'host', 'username', 'password'
    selectors = ModuleType('homeassistant.helpers.selector')
    selectors.selector = lambda value: object
    package = ModuleType('discovery_test_package')
    package.__path__ = [str(PACKAGE)]
    modules = {
        'homeassistant': ha,
        'homeassistant.const': const,
        'homeassistant.helpers': ModuleType('homeassistant.helpers'),
        'homeassistant.helpers.selector': selectors,
        'discovery_test_package': package,
    }
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location(
            'discovery_test_package.config_flow', PACKAGE / 'config_flow.py'
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


flow = load_flow()
CONFIG = {'host': 'checkmk.example', 'site': 'prod', 'username': 'guest', 'password': 'SECRET'}
CONFIG_ENDPOINT = '/domain-types/host_config/collections/all'
HOST_ENDPOINT = '/domain-types/host/collections/all'
SERVICE_ENDPOINT = '/domain-types/service/collections/all'


def response(payload=None, status=200, json_error=None):
    result = MagicMock()
    result.status = status
    result.json = AsyncMock(return_value=payload, side_effect=json_error)
    if status >= 400:
        result.raise_for_status.side_effect = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=status
        )
    result.__aenter__ = AsyncMock(return_value=result)
    result.__aexit__ = AsyncMock(return_value=False)
    return result


class DiscoveryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = MagicMock()
        self.session.__aenter__ = AsyncMock(return_value=self.session)
        self.session.__aexit__ = AsyncMock(return_value=False)
        self.session.post.return_value = response({'value': []})
        self.client_patch = patch.object(flow.aiohttp, 'ClientSession', return_value=self.session)
        self.connector_patch = patch.object(flow.aiohttp, 'TCPConnector')
        self.client_patch.start()
        self.connector_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.addCleanup(self.connector_patch.stop)

    async def test_guest_empty_config_discovers_24_monitoring_hosts_and_metrics(self):
        hosts = [f'host-{i:02}' for i in range(24)]
        self.session.get.side_effect = [
            response({'value': []}),
            response({'value': [{'id': name, 'title': name, 'extensions': {'name': name}}
                                for name in reversed(hosts)]}),
        ]
        self.session.post.return_value = response({'value': [
            {'extensions': {'host_name': hosts[0], 'description': 'CPU', 'perf_data': 'util=5%'}},
            {'host_name': hosts[1], 'description': 'Memory', 'perf_data': 'used=2GB'},
        ]})
        found, services = await flow._async_discover(CONFIG)
        self.assertEqual(found, hosts)
        self.assertEqual(services, [(hosts[0], 'CPU', ('util',)), (hosts[1], 'Memory', ('used',))])
        self.assertTrue(self.session.get.call_args_list[0].args[0].endswith(CONFIG_ENDPOINT))
        self.assertTrue(self.session.get.call_args_list[1].args[0].endswith(HOST_ENDPOINT))
        self.assertTrue(self.session.post.call_args.args[0].endswith(SERVICE_ENDPOINT))
        self.assertEqual(self.session.post.call_args.kwargs['json'], {
            'sites': ['prod'], 'columns': ['host_name', 'description', 'perf_data']})

    async def test_existing_configured_hosts_keep_identifiers_and_skip_fallback(self):
        self.session.get.return_value = response({'value': [
            {'id': 'host-b', 'title': 'Friendly alias'}, {'id': 'Host-a'},
            {'id': 'host-b'}, {'name': 'host-c'}, {'title': 'host-d'},
        ]})
        hosts, services = await flow._async_discover(CONFIG)
        self.assertEqual(hosts, ['Host-a', 'host-b', 'host-c', 'host-d'])
        self.assertEqual(services, [])
        self.session.get.assert_called_once()

    async def test_config_forbidden_uses_monitoring(self):
        self.session.get.side_effect = [response(status=403), response({'value': [{'id': 'host'}]})]
        self.assertEqual((await flow._async_discover(CONFIG))[0], ['host'])

    async def test_empty_both_is_no_hosts_and_does_not_query_services(self):
        self.session.get.return_value = response({'value': []})
        with self.assertRaises(flow.NoHostsError):
            await flow._async_discover(CONFIG)
        self.session.post.assert_not_called()

    async def test_auth_errors_at_each_endpoint(self):
        for endpoint, status in [('config', 401), ('monitoring', 401),
                                 ('monitoring', 403), ('service', 401), ('service', 403)]:
            with self.subTest(endpoint=endpoint, status=status):
                self.session.get.side_effect = None
                self.session.get.return_value = response({'value': [{'id': 'host'}]})
                self.session.post.return_value = response({'value': []})
                if endpoint == 'config':
                    self.session.get.return_value = response(status=status)
                elif endpoint == 'monitoring':
                    self.session.get.side_effect = [response({'value': []}), response(status=status)]
                else:
                    self.session.post.return_value = response(status=status)
                with self.assertRaises(PermissionError):
                    await flow._async_discover(CONFIG)

    async def test_bad_collections_and_host_identifiers(self):
        for payload in (None, [], {}, {'value': None}, {'value': {}},
                        {'value': [None]}, {'value': [{}]}, {'value': [{'id': 42}]}):
            with self.subTest(payload=payload):
                self.session.get.return_value = response(payload)
                with self.assertRaises(ValueError):
                    await flow._async_discover(CONFIG)

    async def test_bad_monitoring_collection_is_invalid(self):
        self.session.get.side_effect = [response({'value': []}), response({'value': [None]})]
        with self.assertRaisesRegex(ValueError, HOST_ENDPOINT):
            await flow._async_discover(CONFIG)

    async def test_bad_service_payloads_are_invalid(self):
        self.session.get.return_value = response({'value': [{'id': 'host'}]})
        for payload in ({}, {'value': [None]}, {'value': [{'host_name': 1}]},
                        {'value': [{'description': []}]}, {'value': [{'perf_data': {}}]}):
            with self.subTest(payload=payload):
                self.session.post.return_value = response(payload)
                with self.assertRaisesRegex(ValueError, SERVICE_ENDPOINT):
                    await flow._async_discover(CONFIG)

    async def test_json_error_is_sanitized(self):
        self.session.get.return_value = response(json_error=ValueError('SECRET response'))
        with self.assertRaisesRegex(ValueError, 'expected a JSON response') as error:
            await flow._async_discover(CONFIG)
        self.assertNotIn('SECRET', str(error.exception))

    async def test_http_errors_and_timeouts_are_not_retried_as_empty_hosts(self):
        for failure in (response(status=500), response(status=404)):
            self.session.get.return_value = failure
            with self.assertRaises(aiohttp.ClientResponseError):
                await flow._async_discover(CONFIG)
        self.session.get.side_effect = TimeoutError
        with self.assertRaises(TimeoutError):
            await flow._async_discover(CONFIG)

    async def test_monitoring_extensions_name_is_supported(self):
        self.session.get.side_effect = [response({'value': []}), response({'value': [
            {'extensions': {'name': 'host'}, 'title': 'Friendly alias'}]})]
        self.assertEqual((await flow._async_discover(CONFIG))[0], ['host'])


class FlowErrorTest(unittest.IsolatedAsyncioTestCase):
    async def test_setup_and_options_errors_and_safe_logging(self):
        cases = [(flow.NoHostsError(), 'no_hosts'),
                 (ValueError('host endpoint: invalid collection'), 'invalid_response'),
                 (PermissionError(), 'invalid_auth'), (TimeoutError(), 'cannot_connect')]
        for cls in (flow.CheckmkConfigFlow, flow.CheckmkOptionsFlowHandler):
            for error, expected in cases:
                with self.subTest(flow=cls.__name__, error=expected):
                    instance = (cls(SimpleNamespace(options={}, data=CONFIG))
                                if cls is flow.CheckmkOptionsFlowHandler else cls())
                    instance.async_show_form = MagicMock(side_effect=lambda **kwargs: kwargs)
                    with patch.object(flow, '_async_discover', AsyncMock(side_effect=error)):
                        with self.assertLogs(flow._LOGGER, level='WARNING') if expected in {
                            'no_hosts', 'invalid_response'} else patch.object(flow._LOGGER, 'debug'):
                            result = await instance._async_connection_step('user', CONFIG)
                    self.assertEqual(result['errors'], {'base': expected})

    async def test_success_reaches_host_selection_for_setup_and_options(self):
        for cls in (flow.CheckmkConfigFlow, flow.CheckmkOptionsFlowHandler):
            instance = (cls(SimpleNamespace(options={}, data=CONFIG))
                        if cls is flow.CheckmkOptionsFlowHandler else cls())
            instance.async_step_hosts = AsyncMock(return_value='hosts form')
            with patch.object(flow, '_async_discover', AsyncMock(return_value=(['host'], []))):
                self.assertEqual(await instance._async_connection_step('user', CONFIG), 'hosts form')
            self.assertEqual(instance._connection_data, CONFIG)

    async def test_real_discovery_logs_endpoint_reason_without_credentials(self):
        instance = flow.CheckmkConfigFlow()
        instance.async_show_form = MagicMock(side_effect=lambda **kwargs: kwargs)
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.get.return_value = response(json_error=ValueError('SECRET response'))
        with patch.object(flow.aiohttp, 'ClientSession', return_value=session):
            with self.assertLogs(flow._LOGGER, level='DEBUG') as logs:
                result = await instance._async_connection_step('user', CONFIG)
        self.assertEqual(result['errors'], {'base': 'invalid_response'})
        output = '\n'.join(logs.output)
        self.assertIn(CONFIG_ENDPOINT, output)
        self.assertIn('expected a JSON response', output)
        for private in ('SECRET', 'guest', 'Authorization', 'Bearer', 'checkmk.example'):
            self.assertNotIn(private, output)

    def test_translations_have_new_error_in_both_flows(self):
        for path in (PACKAGE / 'strings.json', *(PACKAGE / 'translations').glob('*.json')):
            data = json.loads(path.read_text(encoding='utf-8'))
            for section in ('config', 'options'):
                self.assertIn('no_hosts', data[section]['error'])


if __name__ == '__main__':
    unittest.main()
