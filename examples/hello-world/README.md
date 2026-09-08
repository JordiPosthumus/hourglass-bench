# Hello world setup demo

This is a tiny public smoke test, not a meaningful model benchmark. The harness seeds a subtraction-for-addition bug in a small calculator; the agent must repair it and submit. The supplied verifier checks the repair.

From the repository root, run:

```sh
python3 scripts/install_demo.py
./start-hourglass.sh
```

Select `hello-world`, choose your local model, and use one repeat. A correct result confirms that the basic model/tool/verifier path works. Do not treat success on this demo as evidence of broader model capability.

This example is the only task shipped with Hourglass Bench. Bring your own private question bank for actual evaluation.
