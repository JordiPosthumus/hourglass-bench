import copy
import unittest
import stock_pi
import hourglass
import profile_export


def config():
    return {'name':'qwen3.8-fixture','model':'qwen3.8-fixture','base_url':'http://localhost:1234/v1',
            'api_key':'PRIVATE_CREDENTIAL','max_tokens':262144,'context_window':262144,
            'sampling_era':'pi-native-v1','output_budget':'pi','pi_thinking_level':'xhigh',
            'pi_model':{'thinkingLevelMap':{'xhigh':'xhigh'},'samplingParams':{'temperature':1,'top_p':.95}},
            'inference_profile':{'mapping_version':'pi-native-v1','backend':'vllm','backend_version':'fixture','route':{'kind':'direct'}}}


class StockPiTests(unittest.TestCase):
    def test_native_capacities_and_thinking_validate(self):
        cfg=config(); self.assertEqual(hourglass.validate_models({'models':[cfg]}),[])
        definition=stock_pi.model_definition(cfg)
        self.assertEqual(definition['maxTokens'],262144)
        self.assertEqual(definition['contextWindow'],262144)
        self.assertEqual(definition['thinkingLevelMap']['xhigh'],'xhigh')
        self.assertNotIn('api_key',definition)

    def test_budget_or_thinking_payload_override_rejected(self):
        for key in stock_pi.GENERATION_OVERRIDES:
            cfg=config();cfg['pi_model']['samplingParams'][key]=1
            with self.subTest(key=key),self.assertRaises(ValueError):stock_pi.validate(cfg)

    def test_undeclared_or_disabled_thinking_rejected(self):
        for model in ({},{'thinkingLevelMap':{'xhigh':None}},{'reasoning':False}):
            cfg=config();cfg['pi_model']=model
            with self.assertRaises(ValueError):stock_pi.validate(cfg)

    def test_migration_retains_values_provenance_and_capacities(self):
        cfg=config();cfg.pop('pi_model');cfg.pop('pi_thinking_level')
        cfg.update(sampling_era='explicit-v1',output_budget='explicit',inference_profile={
            'mapping_version':'request-api-v1','backend':'vllm','backend_version':'fixture',
            'lane':'thinking','route':{'kind':'direct'},'values':{'temperature':1,'top_p':.95,'top_k':20,'min_p':0,'presence_penalty':0,'repetition_penalty':1,'enable_thinking':True,'preserve_thinking':True,'reasoning_effort':'xhigh'}})
        before=copy.deepcopy(cfg);after=stock_pi.migrate(cfg)
        self.assertEqual(cfg,before)
        self.assertEqual(after['prior_inference_profile'],before['inference_profile'])
        for key in ('api_key','base_url','model','max_tokens','context_window'):self.assertEqual(after[key],before[key])
        self.assertEqual(after['pi_thinking_level'],'xhigh')
        self.assertEqual(after['pi_model']['compat']['chatTemplateKwargs']['preserve_thinking'],True)
        self.assertEqual(after['pi_model']['samplingParams']['temperature'],1)

    def test_export_uses_native_declaration_and_redacts_private_fields(self):
        cfg=config();cfg['pi_model']['compat']={'unknown':'PRIVATE_CREDENTIAL'}
        row={'evaluation_id':'abc','pi_session':{'thinking_level':'xhigh','unknown':'PRIVATE_CREDENTIAL'},
             'settings_capture':{'request_count':1},'requested_settings':[{'values':{'max_tokens':251000,'reasoning_effort':'xhigh'}}]}
        text=profile_export.export({'id':'abc','state':'completed','model_config_snapshot':cfg},[row])
        self.assertNotIn('PRIVATE_CREDENTIAL',text)
        self.assertNotIn('http://localhost',text)
        self.assertNotIn('before_provider_request',text)
        self.assertIn('Select thinking level: `xhigh`',text)
        self.assertIn('incomplete',text)


if __name__=='__main__':unittest.main()
