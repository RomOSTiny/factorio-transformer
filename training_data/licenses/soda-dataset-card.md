---
language:
- en
language_creators:
- machine-generated
annotation_creators:
- machine-generated
license:
- cc-by-4.0
multilinguality:
- monolingual
pretty_name: SODA
size_categories:
- 1M<n<10M
splits:
- name: train
  num_examples: 1191582
- name: valid
  num_examples: 146346
- name: test
  num_examples: 148968
dataset_size: 1486896
source_datasets:
- original
- extended|Atomic10x
tags:
- dialogue
- narrative
- commonsense
task_categories:
- conversational
task_ids:
- dialogue-generation
---

# Dataset Card for 🥤SODA

## Dataset Description
- **Repository:** [Code](https://github.com/skywalker023/sodaverse)
- **Paper:** [SODA: Million-scale Dialogue Distillation with Social Commonsense Contextualization](https://arxiv.org/abs/2212.10465)
- **Point of Contact:** [Hyunwoo Kim](mailto:hyunwook@allenai.org)

## Dataset Summary
🥤SODA is the first publicly available, million-scale, high-quality dialogue dataset covering a wide range of social interactions. Dialogues are distilled from a PLM (InstructGPT; Ouyang et al., 2022) by contextualizing social commonsense knowledge from a knowledge graph (Atomic10x; West et al., 2022). Human evaluation shows that dialogues in SODA are more consistent, specific, and (surprisingly) natural than prior human-authored datasets – e.g., DailyDialog (Li et al., 2017), BlendedSkillTalk (Smith et al., 2020). Also, since social commonsense knowledge encompasses emotional reactions (i.e., the xReact `relation`), SODA includes 385K conversations labeled with 1.7K unique emotions along with information about the experiencer and the cause – i.e., `PersonX` and the `head` event in the symbolic commonsense knowledge triple.

## Languages
English

## Dataset Structure

field | type | description
--- | ---  | ---
`head` | str | the head event in the symbolic commonsense knowledge triple
`relation` | str | the relationship between `head` and `tail` events
`tail` | str | the tail event in the symbolic commonsense knowledge triple
`literal` | str | the symbolic commonsense knowledge in sentence-form
`narrative` | str | narrative based on the `literal`
`dialogue` | list of str | dialogue grounded in the `narrative`
`speakers` | list of str | the speakers for each turn in the `dialogue`
`PersonX` | str | the assigned name for PersonX in the commonsense knowledge triple
`PersonY` | str\|null | the assigned name for PersonY in the commonsense knowledge triple
`PersonZ` | str\|null | the assigned name for PersonZ in the commonsense knowledge triple
`original_index` | int | the original index from Atomic10x
`split` | str | the split information: {train, valid, test}
`head_answer` | str | the answer for whether the `head` is included in the `narrative`: {Yes, Unknown}
`pmi_head_answer` | str | the answer for whether the `head` is included in the `narrative` with point-wise mutual information applied: {Yes, No, Unknown}
`relation_tail_answer` | str | the answer for whether the `relation`-`tail` is included in the `dialogue`: {Yes, No, Unknown}
`pmi_relation_tail_answer` | str | the answer for whether the `relation`-`tail` is included in the `dialogue` with point-wise mutual information applied: {Yes, No, Unknown}


## Dataset Creation

To create 🥤SODA, we distill dialogues from InstructGPT by contextualizing social commonsense knowledge – i.e., adding context information in multiple steps: (1) Retrieve social commonsense from the symbolic commonsense knowledge graph, (2) convert it into sentence form, (3) generate a narrative from the sentence, (4) infer the speakers from the narrative, and finally (5) derive contentful conversation grounded in the narrative and speakers. Anchoring the PLM in commonsense knowledge for deriving conversations offers two key advantages: (1) minimizing nonsensical conversations and (2) maximizing diversity. For more details, please refer to our [paper](https://arxiv.org/abs/2212.10465).


### Further Details, Social Impacts, and Limitations
Please refer to our [paper](https://arxiv.org/abs/2212.10465).

## Trained Model
Using 🥤SODA, we train 🧑🏻‍🚀COSMO: a generalizable conversation agent outperforming previous best-performing agents on both in- and out-of-domain datasets. COSMO-3B is available [here](https://huggingface.co/allenai/cosmo-xl)!

## Additional Information

For a brief summary of our paper, please see this [tweet](https://twitter.com/hyunw__kim/status/1605400305126248448).

### Citation

Please cite our work if you find the resources in this repository useful:
```
@article{kim2022soda,
    title={SODA: Million-scale Dialogue Distillation with Social Commonsense Contextualization},
    author={Hyunwoo Kim and Jack Hessel and Liwei Jiang and Peter West and Ximing Lu and Youngjae Yu and Pei Zhou and Ronan Le Bras and Malihe Alikhani and Gunhee Kim and Maarten Sap and Yejin Choi},
    journal={ArXiv},
    year={2022},
    volume={abs/2212.10465}
}
```