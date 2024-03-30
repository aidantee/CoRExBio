Implemented by Nguyễn Trần Anh Đức, a member of AIDANTE (2023).
# Dataset
1. Download dataset from this link: https://drive.google.com/file/d/1-eDQ1tWpxNjLt-ZOP0htbE700R0q6tzW/view?usp=sharing
2. Unzip into project's folder

# How to install (conda)
1. Create a new environment `cre_biomedical` with python version 3.7
```
conda create -n cre_biomedical python=3.7
```
2. Activate environment `cre_biomedical`
```
conda activate cre_biomedical
```
3. Install packages
```
pip install torch==1.8.1+cu111 torchvision==0.9.1+cu111 torchaudio==0.8.1 -f https://download.pytorch.org/whl/torch_stable.html
pip install torchtext==0.9.1
pip install transformers
pip install scikit-learn
```

# How to run
- Config arguments in file `run.sh`
- Run following command in terminal
```
./run.sh
```
# Result for experiment ID
- Model's performance are saved to folder result\detail_performance\continual_{ID}
- Performance after training i task [T_1, T_2, ..., T_i] is saved to folder result\continual_{ID}\detail_performance\{i}
- Model is saved to folder file result\save_model\model_{ID}
- Memorized samples is saved to file result\save_memorized_samples\memory_{ID}.pkl
- Log during training is saved to file result\detail_training\training_performance_{ID}.txt
