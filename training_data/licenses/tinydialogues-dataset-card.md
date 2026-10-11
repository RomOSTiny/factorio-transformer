---
license: mit
task_categories:
- text-generation
- text2text-generation
language:
- en
pretty_name: TinyDialogues
size_categories:
- 10M<n<100M
tags:
- child-directed speech
- language models
- LLM
- language acquisition
- GPT-2
- RoBERTa
- synthetic data
- TinyDialogues
- BabyLM
- pretraining
- data efficiency
- learning efficiency
- curricularization
- curriculum learning
- data quality
- child language development
- cognitive science
- psychology
---
# Dataset Card for TinyDialogues

TinyDialogues dataset collected as part of the EMNLP 2024 [paper](https://aclanthology.org/2024.emnlp-main.1231/) "Is Child-Directed Speech Effective Training Data for Language Models?" by Steven Y. Feng, Noah D. Goodman, and Michael C. Frank. For more details, please see Appendices A-C in our paper.

### Dataset Description

- **Curated by:** Steven Y. Feng, Noah D. Goodman, and Michael C. Frank [Stanford University]
- **Funded by:** Amazon, Microsoft Accelerating Foundation Models Research (AFMR), NSERC Postgraduate Scholarships – Doctoral (PGS D) program
- **Language(s):** English
- **License:** MIT

### Dataset Sources

- **Repository:** https://github.com/styfeng/TinyDialogues
- **Paper:** https://aclanthology.org/2024.emnlp-main.1231/

## Dataset Structure

Final training and validation data, ordered ascending by age (2, 5, 10, 15). 'individual_age_data.zip' contains individual age examples. The files inside named with 'full_with_metadata' contain all examples for each age including input parameters (e.g. number of participants, convo type) and additional GPT-4 generated metadata such as descriptions of the setting and participants for each conversation.

## Dataset Creation

### Curation Rationale

To provide a fully grammatical and curricularized conversation dataset with restricted vocab.

#### Data Collection and Processing

We used GPT-4 to synthesize approx. 130k child-directed conversations that differ by child age, type, participants, length, and content. Please see Appendices A-C of our [paper](https://aclanthology.org/2024.emnlp-main.1231/) for more details.

## Citation

**BibTeX:**

@inproceedings{feng-etal-2024-child,
    title = "Is Child-Directed Speech Effective Training Data for Language Models?",
    author = "Feng, Steven Y.  and
      Goodman, Noah  and
      Frank, Michael",
    editor = "Al-Onaizan, Yaser  and
      Bansal, Mohit  and
      Chen, Yun-Nung",
    booktitle = "Proceedings of the 2024 Conference on Empirical Methods in Natural Language Processing",
    month = nov,
    year = "2024",
    address = "Miami, Florida, USA",
    publisher = "Association for Computational Linguistics",
    url = "https://aclanthology.org/2024.emnlp-main.1231",
    pages = "22055--22071",
}

## Dataset Card Authors

Steven Y. Feng, Stanford University

## Dataset Card Contact

syfeng@stanford.edu