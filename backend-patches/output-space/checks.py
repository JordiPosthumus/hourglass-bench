#!/usr/bin/env python3
"""Check installed output-space code without model loading or setting changes."""
import argparse
import unittest

parser = argparse.ArgumentParser()
parser.add_argument('--backend', choices=['vllm', 'omlx'], required=True)
args, rest = parser.parse_known_args()

if args.backend == 'vllm':
    from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionRequest
    from vllm.entrypoints.serve.utils.api_utils import get_max_tokens
    from vllm.renderers.params import TokenizeParams
    from vllm.exceptions import VLLMValidationError

    class Checks(unittest.TestCase):
        def test_full_path_and_both_final_converters(self):
            for prompt, requested in [(700, 1000), (850, 999), (999, 1000), (10, 2000)]:
                for stream in [False, True]:
                    for alias in ['max_tokens', 'max_completion_tokens']:
                        with self.subTest(prompt=prompt, requested=requested, stream=stream, alias=alias):
                            # This alias intentionally activates the optional Qwen contract.
                            request = ChatCompletionRequest(model='qwen3.8-flash-next', messages=[{'role':'user','content':'Synthetic input'}], stream=stream, **{alias:requested})
                            ids = [42] * prompt
                            actual = TokenizeParams(1000, requested).apply_post_tokenization(None, {'prompt_token_ids':ids})
                            self.assertIs(actual['prompt_token_ids'], ids)
                            budget = get_max_tokens(1000, requested, prompt, {})
                            self.assertEqual(request.to_sampling_params(budget, {}).max_tokens, 1000-prompt)
                            self.assertEqual(request.to_beam_search_params(budget, {}).max_tokens, 1000-prompt)
        def test_small_omitted_and_server_defaults(self):
            for requested, defaults, override, expected in [(100,{},None,100),(None,{},None,300),(None,{'max_tokens':200},None,200),(1000,{},150,150)]:
                request = ChatCompletionRequest(model='qwen3.8-flash-next', messages=[], max_tokens=requested)
                budget = get_max_tokens(1000, requested, 700, defaults, override)
                self.assertEqual(request.to_sampling_params(budget, defaults).max_tokens, expected)
        def test_full_prompt_and_tokenization_options(self):
            for count in [1000,1001]:
                with self.assertRaises(ValueError): get_max_tokens(1000,1000,count,{})
            with self.assertRaises(VLLMValidationError):
                TokenizeParams(1000,1000).apply_post_tokenization(None,{'prompt_token_ids':[42]*1001})
            for change in [{},{'add_special_tokens':False},{'needs_detokenization':True}]:
                cfg=TokenizeParams(1000,1000).with_kwargs(**change)
                self.assertEqual(cfg.max_output_tokens,1000)
                self.assertEqual(cfg.get_encode_kwargs()['max_length'],1001)
            tokenizer=type('Tokenizer',(),{'truncation_side':'right','pad_token_id':0})()
            cfg=TokenizeParams(1000,800,truncate_prompt_tokens=-1)
            self.assertEqual(cfg._token_truncation(tokenizer,list(range(700))),list(range(200)))
            self.assertEqual(len(TokenizeParams(1000,800,pad_prompt_tokens=-1)._token_padding(tokenizer,[1])),200)
else:
    from omlx.qwen_contract import resolve_qwen_output_budget, QwenContractError
    class Checks(unittest.TestCase):
        def test_exact_upper_bound(self):
            for explicit in [True,False]:
                for prompt,requested,expected in [(700,1000,300),(700,100,100),(999,1000,1),(10,2000,990)]:
                    self.assertEqual(resolve_qwen_output_budget(prompt,requested,1000,explicit),expected)
        def test_full_input_and_invalid_output(self):
            for prompt,requested in [(1000,1),(1001,1),(10,0),(10,-1)]:
                with self.assertRaises(QwenContractError):resolve_qwen_output_budget(prompt,requested,1000,True)

unittest.main(argv=['checks.py',*rest], verbosity=2)
