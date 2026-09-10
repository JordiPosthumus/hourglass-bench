import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hardware_records

class HardwareRecordTests(unittest.TestCase):
    def test_local_identity_stable_without_hostname_or_serial(self):
        with tempfile.TemporaryDirectory() as d,patch.object(hardware_records.platform,'system',return_value='Darwin'),patch.object(hardware_records.platform,'processor',return_value='Chip'),patch.object(hardware_records.subprocess,'check_output',side_effect=['Chip','1024','4','{}']*2):
            root=Path(d);a=hardware_records.capture(root,{'base_url':'http://127.0.0.1:1234/v1','inference_location':'local'});b=hardware_records.capture(root,{'base_url':'http://localhost:5111/v1','inference_location':'local'})
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

    def test_owner_amendment_is_backed_up_and_overrides_frozen_record(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);original={'machine_key':'old','label':'Original','source':'local system query'}
            manifest={'id':'run','hardware':original};before=json.dumps(manifest)
            result=hardware_records.save_user_record(root,manifest,{'machine_key':'new','label':'Remote machine','chip':'Test CPU','memory_gib':'128','cpu_cores':'20','gpu':'Test GPU'},['old'],hardware_records.revision(original))
            self.assertEqual(result['memory_bytes'],128*1024**3);self.assertEqual(result['cpu_cores'],20)
            self.assertEqual(hardware_records.recorded(root,manifest),result);self.assertEqual(json.dumps(manifest),before)
            self.assertEqual(len(list((root/'backups').glob('hardware-amendment-*/previous-effective-hardware.json'))),1)
            with self.assertRaisesRegex(ValueError,'changed since'):
                hardware_records.save_user_record(root,manifest,{'machine_key':'old','label':'Stale'},['old'],hardware_records.revision(original))

    def test_invalid_hardware_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m={'id':'run'};rev=hardware_records.revision(hardware_records.recorded(root,m))
            for fields in [{'machine_key':'new','label':'Example','memory_gib':'-1'},{'machine_key':'new','label':'Example','cpu_cores':'1.5'},{'machine_key':'unlisted','label':'Example'}]:
                with self.assertRaises(ValueError):hardware_records.save_user_record(root,m,fields,[],rev)
            self.assertFalse((root/'hardware-records').exists())
