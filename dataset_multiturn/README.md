---
dataset_info:
  features:
  - name: id
    dtype: string
  - name: conversations
    list:
    - name: from
      dtype: string
    - name: value
      dtype: string
  - name: category
    dtype: string
  - name: subcategory
    dtype: string
  - name: task
    dtype: string
  splits:
  - name: train
    num_bytes: 17598897
    num_examples: 1893
  download_size: 7194968
  dataset_size: 17598897
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train-*
---
