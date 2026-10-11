---
license: cc-by-4.0
task_categories:
- text2text-generation
language:
- en
size_categories:
- 10K<n<100K
---

# Dataset Card for SPC: Synthetic-Persona-Chat Dataset

Abstract from the paper introducing this dataset: 
> High-quality conversational datasets are essential for developing AI models that can communicate with users. One way to foster deeper interactions between a chatbot and its user is through personas, aspects of the user's character that provide insights into their personality, motivations, and behaviors. Training Natural Language Processing (NLP) models on a diverse and comprehensive persona-based dataset can lead to conversational models that create a deeper connection with the user, and maintain their engagement. In this paper, we leverage the power of Large Language Models (LLMs) to create a large, high-quality conversational dataset from a seed dataset. We propose a Generator-Critic architecture framework to expand the initial dataset, while improving the quality of its conversations. The Generator is an LLM prompted to output conversations. The Critic consists of a mixture of expert LLMs that control the quality of the generated conversations. These experts select the best generated conversations, which we then use to improve the Generator. We release Synthetic-Persona-Chat, consisting of 20k conversations seeded from Persona-Chat. We evaluate the quality of Synthetic-Persona-Chat and our generation framework on different dimensions through extensive experiments, and observe that the losing rate of Synthetic-Persona-Chat against Persona-Chat during Turing test decreases from 17.2% to 8.8% over three iterations.

## Dataset Details

### Dataset Description

> We introduce the Synthetic-Persona-Chat dataset, a persona-based conversational dataset, consisting of two parts. The first part, consisting of 4,723 personas and 10,906 conversations, is an extension to Persona-Chat, which has the same user profile pairs as Persona-Chat but new synthetic conversations, with the same train/validation/test split as Persona-Chat. The second part is new synthetic personas and synthetic conversations based on that, consisting of 5,648 synthetic personas and 11,001 conversations. Synthetic-Persona-Chat is created using the Generator-Critic framework introduced in Faithful Persona-based Conversational Dataset Generation with Large Language Models.

Each conversation in the dataset has the following format:
```
{
  "User 1 Persona":[],
  "User 2 Persona":[],
  "Conversation":[]
}
```

### Dataset Sources 

<!-- Provide the basic links for the dataset. -->

- **Repository:** https://github.com/google-research-datasets/Synthetic-Persona-Chat/tree/main
- **Paper:** https://arxiv.org/abs/2312.10007


## Citation 


**BibTeX:**

```@misc{jandaghi2023faithful,
      title={Faithful Persona-based Conversational Dataset Generation with Large Language Models}, 
      author={Pegah Jandaghi and XiangHai Sheng and Xinyi Bai and Jay Pujara and Hakim Sidahmed},
      year={2023},
      eprint={2312.10007},
      archivePrefix={arXiv},
      primaryClass={cs.CL}
}
```