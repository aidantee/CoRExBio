import torchtext
import torch
import json
from utils import print_execute_time
import os
import random
from itertools import combinations

class data_prefetcher():
    def __init__(self, loader):
        self.loader = iter(loader)
        self.stream = torch.cuda.Stream()
        self.preload()

    def preload(self):
        try:
            self.next_data = next(self.loader)
        except StopIteration:
            self.next_input = None
            return
        with torch.cuda.stream(self.stream):
            self.next_data = self.next_data.cuda(non_blocking=True)

    def next(self):
        torch.cuda.current_stream().wait_stream(self.stream)
        data = self.next_data
        self.preload()
        return data


def statistics_corpus(train_file, relation_list):
    with open(train_file, "r") as f:
        train_data = f.readlines()

    num_relation_yes_dic = {}  # how many yes cases in each relation
    for relation in relation_list:
        num_relation_yes_dic.setdefault(relation, 0)

    total_relation_yes_num = 0
    total_entitiy_yes_no_pair_num = 0
    for i in train_data:
        data_dic = eval(i)
        # entity_combine_len = len(list(combinations(data_dic["sampled_entity_span"], 2)))
        entity_combine_len = len(list(combinations(data_dic["sep_entity"], 2)))
        total_entitiy_yes_no_pair_num += entity_combine_len
        for k, v in data_dic.items():
            if k in relation_list:
                num_relation_yes_dic[k] = num_relation_yes_dic[k] + len(v)
                total_relation_yes_num+= len(v)

    # the ratio of yes cases of this relation /  yes cases of all relation
    ratio_relation_dic = num_relation_yes_dic.copy()
    ratio_relation_dic.update((k,round(v/total_relation_yes_num,5)) for k,v in ratio_relation_dic.items())

    yes_no_relation_dic = num_relation_yes_dic.copy()
    yes_no_relation_dic.update( (k, [1-round(v / total_entitiy_yes_no_pair_num, 5), round(v / total_entitiy_yes_no_pair_num, 5)]) for k,v in yes_no_relation_dic.items())

    return ratio_relation_dic, yes_no_relation_dic


def get_data_ID_2_corpus_dic(corpus_list):
    data_ID_2_corpus_dic = {}
    for corpus in corpus_list:
        combining_data_files_list = [os.path.join('../data',  corpus, "BIOES", "base", corpus+'_train_base_model_data.json'),
                                     os.path.join('../data',  corpus, "BIOES", "base", corpus+'_valid_base_model_data.json'),
                                     os.path.join('../data',  corpus, "BIOES", "base", corpus+'_test_base_model_data.json')]
        for file in combining_data_files_list:
            with open(file, "r") as f:
                data_list = f.readlines()
            for data in data_list:
                data_ID_2_corpus_dic[eval(data)["ID"]] = corpus
    return data_ID_2_corpus_dic


def get_corpus_file_dic(all_data_flag, corpus_list, Task_list, base_large, Test_TAC_flag):
    if Test_TAC_flag:
        corpus_list.append("TAC2019")

    with open("../data/corpus_information.json", "r") as f:
        raw_corpus_file_dic = eval(f.read())

    sep_corpus_file_dic = {}
    for corpus, sub_task_dic in raw_corpus_file_dic.items():
        sep_corpus_file_dic.setdefault(corpus, {})
        for task in Task_list:
            if task == "entity_span":
                v_list = ["entity_span"]
            if task == "entity_type":
                v_list = raw_corpus_file_dic[corpus]['entity_type_list']
                v_list = ["only_entity_type_"+i for i in v_list]
            if task == "entity_span_and_type":
                v_list = raw_corpus_file_dic[corpus]['entity_type_list']
                v_list = ["joint_entity_type_"+i for i in v_list]
            if task == "relation":
                v_list = raw_corpus_file_dic[corpus]['relation_list']
                v_list = ["relation_"+i for i in v_list]
            sep_corpus_file_dic[corpus][task]=v_list

    # task list may not contain all corpus in corpus_information.json
    pick_corpus_file_dic = {}
    for corpus in corpus_list:
        pick_corpus_file_dic[corpus] = raw_corpus_file_dic[corpus]

    return_corpus_file_dic = {}
    # new file address
    if all_data_flag:
        combining_data_files_list = [os.path.join('../data', 'Multi_Task_Training', base_large, str(corpus_list)+'_train_base_model_data.json'),
                                     os.path.join('../data', 'Multi_Task_Training', base_large, str(corpus_list)+'_valid_base_model_data.json'),
                                     os.path.join('../data', 'Multi_Task_Training', base_large, str(corpus_list)+'_test_base_model_data.json')]
    else:
        combining_data_files_list = [os.path.join('../data', 'Multi_Task_Training', base_large, 'test', str(corpus_list)+'_train_base_model_data.json'),
                                     os.path.join('../data', 'Multi_Task_Training', base_large, 'test', str(corpus_list)+'_valid_base_model_data.json'),
                                     os.path.join('../data', 'Multi_Task_Training', base_large, 'test', str(corpus_list)+'_test_base_model_data.json')]

    entity_type_list = []
    relation_list = []
    for name, value in pick_corpus_file_dic.items():
        entity_type_list.extend(value["entity_type_list"])
        relation_list.extend(value["relation_list"])
    entity_type_list = list(set(entity_type_list))
    relation_list = list(set(relation_list))

    return_corpus_file_dic[str(corpus_list)] = (entity_type_list, relation_list, combining_data_files_list)

    return return_corpus_file_dic, sep_corpus_file_dic, pick_corpus_file_dic, combining_data_files_list, entity_type_list, relation_list

def make_model_data(base_large, pick_corpus_file_dic, combining_data_files_list, entity_type_list, relation_list, all_data_flag):
    # if all file exist, don't generate new
    temp_flag = 1
    for file in combining_data_files_list:
        if os.path.exists(file):
            temp_flag = temp_flag* 1
        else:
            temp_flag = temp_flag* 0

    if temp_flag==0:
        for file in combining_data_files_list:
            if os.path.exists(file):
                os.remove(file)

        train_data = []
        valid_data = []
        test_data = []
        data_list = [train_data, valid_data, test_data]
        for corpus_name, corpus_inform in pick_corpus_file_dic.items():
            corpus_train_valid_test_file = corpus_inform["file_list"]
            for index, raw_train_valid_test_file in enumerate(corpus_train_valid_test_file):
                if all_data_flag:
                    raw_train_valid_test_file = os.path.join('../data', corpus_name, 'BIOES', base_large, raw_train_valid_test_file)
                else:
                    raw_train_valid_test_file = os.path.join('../data', corpus_name, 'BIOES', base_large, 'test', raw_train_valid_test_file)

                if base_large=="large":
                    raw_train_valid_test_file=raw_train_valid_test_file.replace("base", "large")
                f = open(raw_train_valid_test_file, 'r', encoding='utf-8')
                one_task_data = f.readlines()
                f.close()
                data_list[index].extend(one_task_data)

        for index, combining_data_files in enumerate(combining_data_files_list):
            with open(combining_data_files, 'w', encoding='utf-8') as multi_task_file:
                # random.shuffle(data_list[index])
                writen_data = data_list[index]

                for one_record in writen_data:
                    one_record = eval(one_record)
                    sent_len = len(one_record["tokens"])
                    for entity_type in entity_type_list:
                        if "only_entity_type_"+entity_type not in one_record.keys():
                            one_record["only_entity_type_"+entity_type] = []
                        if "joint_entity_type_"+entity_type not in one_record.keys():
                            # need improvment, if we padding in memory, it will be quicker
                            one_record["joint_entity_type_"+entity_type] = ["O"] * sent_len
                    for relation in relation_list:
                        if "relation_"+relation not in one_record.keys():
                            one_record["relation_"+relation] = []

                    multi_task_file.write(json.dumps(dict(sorted(one_record.items(), key=lambda item:len(item[0])))))
                    multi_task_file.write('\n')


def prepared_NER_data(BATCH_SIZE, device, tokenizer, file_train_valid_test_list, entity_type_num_list):

    ID_fileds = torchtext.data.Field(batch_first=True, use_vocab=False, sequential=False)
    TOEKNS_fileds = torchtext.data.Field(batch_first=True, use_vocab=False, pad_token=tokenizer.pad_token_id, unk_token=tokenizer.unk_token_id)

    TAGS_entity_span_fileds = torchtext.data.Field(dtype=torch.long, batch_first=True, pad_token= tokenizer.pad_token, unk_token=None)
    TAGS_entity_span_fileds_dic = {"entity_span" :("entity_span", TAGS_entity_span_fileds)}

    TAGS_sep_entity_fileds = torchtext.data.Field(dtype=torch.long, batch_first=True, unk_token=None,  pad_token=tokenizer.pad_token)
    TAGS_sep_entity_fileds_dic = {"sep_entity" :("sep_entity", TAGS_sep_entity_fileds)}

    TAGS_sampled_entity_span_fileds = torchtext.data.Field(dtype=torch.long, batch_first=True, unk_token=None,  pad_token=tokenizer.pad_token)
    TAGS_sampled_entity_span_fileds_dic = {"sampled_entity_span" :("sampled_entity_span", TAGS_sampled_entity_span_fileds)}

    TAGS_only_Entity_Type_fileds_dic = {}
    for entity in entity_type_num_list:
        TAGS_only_Entity_Type_fileds_dic["only_entity_type_"+entity] = ("only_entity_type_"+entity,
                                                                        torchtext.data.Field(dtype=torch.long, batch_first=True, pad_token= tokenizer.pad_token, unk_token=None))

    TAGS_joint_Entity_Type_fileds_dic = {}
    for entity in entity_type_num_list:
        TAGS_joint_Entity_Type_fileds_dic["joint_entity_type_"+entity] = ("joint_entity_type_"+entity,
                                                                          torchtext.data.Field(dtype=torch.long, batch_first=True, pad_token= tokenizer.pad_token, unk_token=None))

    fileds = {}
    fileds['ID'] = ('ID', ID_fileds)
    fileds['tokens'] = ('tokens', TOEKNS_fileds)
    fileds['entity_span'] = ('entity_span', TAGS_entity_span_fileds)
    fileds['sep_entity'] = ('sep_entity', TAGS_sep_entity_fileds)
    fileds['sampled_entity_span'] = ('sampled_entity_span', TAGS_sampled_entity_span_fileds)
    fileds.update(TAGS_only_Entity_Type_fileds_dic)
    fileds.update(TAGS_joint_Entity_Type_fileds_dic)

    train_file = file_train_valid_test_list[0]
    valid_file = file_train_valid_test_list[1]
    test_file = file_train_valid_test_list[2]
    train_set, valid_set, test_set = torchtext.data.TabularDataset.splits(path="", train=train_file, validation = valid_file,
                                                                      test=test_file, format="json", fields=fileds)


    TAGS_entity_span_fileds.build_vocab(train_set, valid_set, test_set)
    TAGS_sep_entity_fileds.build_vocab(train_set, valid_set, test_set)
    TAGS_sampled_entity_span_fileds.build_vocab(train_set, valid_set, test_set)

    for entity, filed in TAGS_only_Entity_Type_fileds_dic.items():
        filed[1].build_vocab(train_set, valid_set, test_set)

    for entity, filed in TAGS_joint_Entity_Type_fileds_dic.items():
            filed[1].build_vocab(train_set, valid_set, test_set, specials=["S", "B", "I", "E"])

    train_iterator, valid_iterator, test_iterator = torchtext.data.BucketIterator.splits(
            [train_set, valid_set, test_set], batch_size=BATCH_SIZE, sort=False, shuffle=True,
            repeat=False, device=device)
    return train_iterator, valid_iterator, test_iterator, TOEKNS_fileds, \
           TAGS_entity_span_fileds_dic, TAGS_only_Entity_Type_fileds_dic, TAGS_joint_Entity_Type_fileds_dic, \
           TAGS_sampled_entity_span_fileds_dic, TAGS_sep_entity_fileds_dic


def prepared_RC_data(BATCH_SIZE, device, tokenizer, file_train_valid_test_list, relation_list):

    ID_fileds = torchtext.data.Field(batch_first=True, use_vocab=False, sequential=False)
    TOEKNS_fileds = torchtext.data.Field(batch_first=True, use_vocab=False, pad_token=tokenizer.pad_token_id, unk_token=tokenizer.unk_token_id)

    TAGS_sampled_entity_span_fileds = torchtext.data.Field(dtype=torch.long, batch_first=True, unk_token=None,  pad_token=tokenizer.pad_token)
    TAGS_sampled_entity_span_fileds_dic = {"sampled_entity_span" :("sampled_entity_span", TAGS_sampled_entity_span_fileds)}

    TAGS_Relation_pair_fileds_dic = {}
    for relation in relation_list:
        TAGS_Relation_pair_fileds_dic["relation_"+relation] = ("relation_"+relation,
                                                               torchtext.data.Field(dtype=torch.long, batch_first=True, pad_token= tokenizer.pad_token, unk_token=None))

    fileds = {}
    fileds['ID'] = ('ID', ID_fileds)
    fileds['tokens'] = ('tokens', TOEKNS_fileds)
    fileds['sampled_entity_span'] = ('sampled_entity_span', TAGS_sampled_entity_span_fileds)
    fileds.update(TAGS_Relation_pair_fileds_dic)

    train_file = file_train_valid_test_list[0]
    valid_file = file_train_valid_test_list[1]
    test_file = file_train_valid_test_list[2]
    train_set, valid_set, test_set = torchtext.data.TabularDataset.splits(path="", train=train_file, validation = valid_file,
                                                                      test=test_file, format="json", fields=fileds)

    TAGS_sampled_entity_span_fileds.build_vocab(train_set, valid_set, test_set)

    for relation, filed in TAGS_Relation_pair_fileds_dic.items():
        filed[1].build_vocab(train_set, valid_set, test_set)

    train_iterator, valid_iterator, test_iterator = torchtext.data.BucketIterator.splits(
        [train_set, valid_set, test_set], batch_size=BATCH_SIZE, sort=False, shuffle=True,
        repeat=False, device=device)

    return train_iterator, valid_iterator, test_iterator, TOEKNS_fileds, TAGS_Relation_pair_fileds_dic, TAGS_sampled_entity_span_fileds_dic


@print_execute_time
def test_load(iterator):
    for batch in iterator:
        print(batch.tokens)
        print(batch.entity_span)
        print(batch.entity_span)
        break


if __name__ == '__main__':
    BATCH_SIZE = 100
    os.environ["CUDA_VISIBLE_DEVICES"] = "2"
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    from transformers import *
    bert_model = "base"
    if bert_model == "base":
        model_path = "/home/hk/workshop_43/Data/embedding/biobert_base"
        tokenizer = BertTokenizer.from_pretrained(model_path)
    elif bert_model == "large":
        model_path = "/home/hk/workshop_43/Data/embedding/biobert_large"
        tokenizer = BertTokenizer.from_pretrained(model_path)

    all_data_flag = False
    corpus_list = ["DDI"]
    # Task_list = ["entity_span", "entity_type", "entity_span_and_type", "relation"]
    Task_list = ["entity_span", "entity_type", "relation"]
    train_way = "Multi_Task_Training"
    corpus_file_dic, sep_corpus_file_dic = get_corpus_file_dic(all_data_flag, corpus_list, train_way, Task_list)
    print(corpus_file_dic)
    for corpus_name, (entity_type_num_list, relation_list, file_train_valid_test_list) in corpus_file_dic.items():
        train_iterator, valid_iterator, test_iterator, \
        TOEKNS_fileds, TAGS_BIOES_fileds_dic, TAGS_only_Entity_Type_fileds_dic, TAGS_joint_Entity_Type_fileds_dic, \
        TAGS_Relation_pair_fileds_dic, ratio_relation_list, yes_no_relation_list, TAGS_sampled_entity_span_fileds_dic, _ \
            = prepared_data(4, device, tokenizer, file_train_valid_test_list, entity_type_num_list, relation_list)

        a = test_load(train_iterator)














