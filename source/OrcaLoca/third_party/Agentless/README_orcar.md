# Agentless experiments on SWE-Bench as integration of Orcar

In this document, we will go through the steps to generate the patches on SWE-bench. 
Currently, only [SWE-Bench Lite](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite) is supported.

## 🐈 Prerequisite

Before running this repo as integration of Orcar, please make sure you have either followed the instructions under OrcarLLM/evaluation/orcar_agentless, or have the files below prepared:
1. results/swe-bench-lite/edit_location_individual/loc_orcar_outputs.jsonl
2. target_inst_ids.json

## 🐈 Setup

First create the environment 

```shell
cd Agentless
git checkout orcar

conda create -n agentless python=3.11 
conda activate agentless
pip install -r requirements.txt
export PYTHONPATH=$PYTHONPATH:$(pwd)
```

Then export your Anthropic API key 
```shell
export ANTHROPIC_API_KEY={key_here}
```

> [!TIP]
> 
> We use multiple threads (controllable via `--num_threads`) to speed up the Agentless process 

## 😼 Repair

Using the 4 sets of edit locations from before, we now perform repair. 

**Agentless** generates multiple patches per issue (controllable via parameters) and then perform majority voting with patch validation to select the final patch for submission 

Run the following command to generate the patches:

> [!TIP]
> Make sure you have
> ```shell
> export PYTHONPATH=$PYTHONPATH:$(pwd)
> ```
> set up correctly, or an error may occur like:
> ```shell
> ModuleNotFoundError: No module named 'agentless'
> ```

```shell
python agentless/repair/repair.py --loc_file results/swe-bench-lite/edit_location_individual/loc_orcar_outputs.jsonl \
                                  --output_folder results/swe-bench-lite/repair_sample_orcar \
                                  --loc_interval \
                                  --top_n=3 \
                                  --context_window=10 \
                                  --max_samples 40  \
                                  --cot \
                                  --str_replace_format \
                                  --gen_and_process \
                                  --num_threads 2
```

This commands generate 40 samples (1 greedy and 39 via temperature sampling) as defined `--max_samples 40`. The `--context_window` indicates the amount of code lines before and after each localized edit location we provide to the model for repair. The patches are saved in `results/swe-bench-lite/repair_sample_orcar/output.jsonl`, which contains the raw output of each sample as well as any trajectory information (e.g., number of tokens). The complete logs are also saved in `results/swe-bench-lite/repair_sample_orcar/repair_logs/` 

## 😸 Patch Validation and Selection 

Since Agentless generates multiple candidate patches per issue, we need a way to select a final patch for submission.

To do this, Agentless leverages both regression tests that exist in the codebase as well as generating new reproduction tests that can verify if the patch can solve the original issue.

#### Regression test selection

We first select a set of regression tests (tests that already exist in the repository and pass on the original codebase) to run.

Run the following command to get a list of passing tests in the original codebase:

```shell
python agentless/test/run_regression_tests.py --run_id generate_regression_tests \
                                              --output_file results/swe-bench-lite/passing_tests.jsonl 
```

This will generate a list of passing tests at `results/swe-bench-lite/passing_tests.jsonl`

> [!NOTE]
> 
> We do not use any of provided PASS_TO_PASS field in the SWE-bench benchmark
> 
> We select tests from the complete list of tests which can pass in the original repository

Next, we ask the LLM to remove any tests which should not be ran with the following command:

```shell
python agentless/test/select_regression_tests.py --passing_tests results/swe-bench-lite/passing_tests.jsonl \
                                                 --output_folder results/swe-bench-lite/select_regression 
```

This will produce a list of final regression tests in `results/swe-bench-lite/select_regression/output.jsonl` with the logs at `results/swe-bench-lite/select_regression/select_test_logs`

We can run this on all the patches generate, repeated for each repair run (i.e., by changing `folder`):

```shell
folder=results/swe-bench-lite/repair_sample_orcar
for num in {0..39..1}; do
    run_id_prefix=$(basename $folder); 
    python agentless/test/run_regression_tests.py --regression_tests results/swe-bench-lite/select_regression/output.jsonl \
                                                  --predictions_path="${folder}/output_${num}_processed.jsonl" \
                                                  --run_id="${run_id_prefix}_regression_${num}" --num_workers 10;
done
```

This will output the regression test results in the same folder as the repair results. `results/swe-bench-lite/repair_sample_orcar/output_{i}_regression_test_results.jsonl` contains the regression test results for each patch number (`i`). 

> [!NOTE]
> 
> We also perform post-processing to generate the complete git-diff patch for each repair sample.
> 
> You can find the individual patch in `results/repair/output_{i}_processed.jsonl` where `i` is the sample number. 

#### Reproduction test generation

In addition to the regression tests, Agentless also generates a reproduction test that attempt to check if the patch can solve the original issue.

Similar to patch generation, Agentless also generates multiple samples of reproduction tests, and then perform selection:
```shell
python agentless/test/generate_reproduction_tests.py --max_samples 40 \
                                                     --output_folder results/swe-bench-lite/reproduction_test_samples \
                                                     --num_threads 10 
```

This will generate 40 samples (1 greedy + 39 temperature sampling) per issue. The generated reproduction tests can be found in `results/swe-bench-lite/reproduction_test_samples/output.jsonl`. The corresponding logs can be found in `results/swe-bench-lite/reproduction_test_samples/generating_test_logs/`.

Now we will execute each of these generated tests on the original repository to see if they can reproduce the original issue.

```shell
for st in {0..36..4}; do   en=$((st + 3));   
        echo "Processing ${st} to ${en}";   
        for num in $(seq $st $en); do     
            echo "Processing ${num}";     
            python agentless/test/run_reproduction_tests.py --run_id="reproduction_test_generation_filter_sample_${num}" \
                                                            --test_jsonl="results/swe-bench-lite/reproduction_test_samples/output_${num}_processed_reproduction_test.jsonl" \
                                                            --num_workers 6 \
                                                            --testing;
done & done
```

> [!WARNING]
> 
> In the above command we execute multiple SWE-bench evaluations in parallel, please ensure that your machine is able to handle that
>
> If not, you may want to reduce the amount of parallelization 

This produces verification results for each tests in the same folder: `results/swe-bench-lite/reproduction_test_samples/`

We then perform majority voting to select one reproduction test per issue:

```shell
python agentless/test/generate_reproduction_tests.py --max_samples 40 \
                                                     --output_folder results/swe-bench-lite/reproduction_test_samples \
                                                     --output_file reproduction_tests.jsonl \
                                                     --select
```

This will generate the reproduction test file at: `results/swe-bench-lite/reproduction_test_samples/reproduction_tests.jsonl`

Finally, we evaluate the generated patches on the selected reproduction test. Similar to regression test execution, this is repeated for each repair run (i.e., by changing `folder`):

```shell
folder=results/swe-bench-lite/repair_sample_orcar
for num in {0..39..1}; do
    run_id_prefix=$(basename $folder); 
    python agentless/test/run_reproduction_tests.py --test_jsonl results/swe-bench-lite/reproduction_test_samples/reproduction_tests.jsonl \
                                                    --predictions_path="${folder}/output_${num}_processed.jsonl" \
                                                    --run_id="${run_id_prefix}_reproduction_${num}" --num_workers 10;
done
```

 This will output the reproduction test results in the same folder as the repair results. `results/swe-bench-lite/repair_sample_orcar/output_{i}_reproduction_test_results.jsonl` contains the reproduction test results for each patch number (`i`). 


#### Reranking and patch selection 

Finally, using the regression and reproduction test results, Agentless performs reranking to select the final patch for submission.

Run the following command (`--regression` indicates we are using regression tests for selection `--reproduction` indicates we are using the reproduction tests for selection)

```shell
python agentless/repair/rerank.py --patch_folder results/swe-bench-lite/repair_sample_orcar/ \
                                  --num_samples 40 \
                                  --deduplicate \
                                  --regression \
                                  --reproduction
```

This command will produced the `all_preds.jsonl` that contains the final selected patch for each instance_id which you can then directly use your favorite way of testing SWE-bench for evaluation!


## 💰 Cost 

To measure the cost of running Agentless, we have provided helpful utilities. 

For each of the `output.jsonl` files produced for each of the steps (including substeps), run the following command:

```shell
python dev/util/cost.py --output_file example_step/output.jsonl 
```
