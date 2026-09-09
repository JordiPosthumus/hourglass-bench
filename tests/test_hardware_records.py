import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hardware_records

class HardwareRecordTests(unittest.TestCase):
    def test_local_identity_stable_without_hostname_or_serial(self):
        with tempfile.TemporaryDirectory() as d,patch.object(hardware_records.platform,'system',return_value='Darwin'),patch.object(hardware_records.platform,'processor',return_value='Chip'),patch.object(hardware_records.subprocess,'check_output',side_effect=['Chip','1024','4','{}']*2):
            root=Path(d);a=hardware_records.capture(root,{'base_url':'http://127.0.0.1:1234/v1'});b=hardware_records.capture(root,{'base_url':'http://localhost:5111/v1'})
            self.assertEqual(a['machine_key'],b['machine_key']);self.assertEqual(a['cpu_cores'],4)
            self.assertNotIn('hostname',a);self.assertNotIn('serial',a)

    def test_remote_never_inherits_controller_hardware(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cfg={'base_url':'http://server.example/v1'}
            self.assertIsNone(hardware_records.capture(root,cfg))
            (root/'hardware-profiles.json').write_text(json.dumps({cfg['base_url']:{'machine_id':'machine-b','label':'Spark fixture','chip':'fixture','api_key':'SECRET'}}))
            result=hardware_records.capture(root,cfg)
            self.assertEqual(result['label'],'Spark fixture');self.assertNotIn('SECRET',json.dumps(result))
            self.assertNotIn('server.example',json.dumps(result))

    def test_unknown_runs_are_not_combined_as_one_machine(self):
        with tempfile.TemporaryDirectory() as d:
            a=hardware_records.recorded(Path(d),{'id':'a'});b=hardware_records.recorded(Path(d),{'id':'b'})
            self.assertNotEqual(a['machine_key'],b['machine_key'])
