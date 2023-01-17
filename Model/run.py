#!/usr/bin/python3.7
# -*- coding: utf-8 -*-
import warnings
import sys
import shutil
import argparse
import os
import math
import copy
import random
import numpy as np
from utils import print_execute_time, record_pred_str_res, Logger, record_each_performance, recored_detail_performance, \
    EMA, get_entity_type_rep_dic, log_gradient_updates, log_parameter_and_gradient_statistics
from metric import report_performance
from my_modules import My_Entity_Span_Classifier, My_Entity_Type_Classifier, My_Entity_Span_And_Type_Classifier, My_Relation_Classifier, My_Bert_Encoder, My_Model
from data_loader import prepared_NER_data, prepared_RC_data, get_corpus_file_dic, make_model_data

parser = argparse.ArgumentParser(description="Bert Model")
parser.add_argument('--GPU', default="0", type=str)
parser.add_argument('--All_data', action='store_true', default=False) # True False
parser.add_argument('--BATCH_SIZE', default=8, type=int)

parser.add_argument('--bert_model', default="base", type=str, help="base, large")
parser.add_argument('--Task_list', default=["entity_span", "entity_type", "relation"], nargs='+', help=["entity_span", "entity_type", "entity_span_and_type", "relation"])
parser.add_argument('--Task_weights_dic', default="{'entity_span':0.4, 'entity_type':0.2,  'relation':0.4}", type=str)

parser.add_argument('--Corpus_list', default=["DDI", "CPR", "Twi_ADE", "ADE"], nargs='+', help=["DDI", "Twi_ADE", "ADE", "CPR"])
parser.add_argument('--Random_ratio', default=1, type=float, help=">1 means mask all data from other corpus")
parser.add_argument('--Group_num', default=40, type=int)
parser.add_argument('--Training_way', default="Multi_Task_Training", type=str, help="Multi_Task_Training, Multi_Task_continual_Training")
parser.add_argument('--Test_flag', action='store_true', default=False, help=[False, True])
parser.add_argument('--Test_TAC_flag', action='store_true', default=False, help=[False, True])  #"TAC2019"
parser.add_argument('--Inner_test_TAC_flag', action='store_true', default=False, help=[False, True])
parser.add_argument('--Test_Corpus', default=["TAC2019"], nargs='+', help=["ADE", "Twi_ADE", "DDI", "CPR", "TAC2019"])  #TAC
parser.add_argument('--Test_model_file', type=str, default="../result/save_model/Model_['--ID', '33333', '--GPU', '2', '--All_data', '--Entity_Prep_Way', 'entitiy_type_marker']")

parser.add_argument('--Share_embedding', action='store_true', default=False, help=[False, True])
parser.add_argument('--Entity_Prep_Way', default="standard", type=str, help=["standard", "entitiy_type_marker", "entity_type_embedding"])
parser.add_argument('--If_add_prototype', action='store_true', default=True) # True False
parser.add_argument('--If_soft_share', action='store_true', default=False) # True False
parser.add_argument('--Pick_lay_num', default=-1, type=int,  help="-1 means last layer")

parser.add_argument('--Average_Time', default=1, type=int)
parser.add_argument('--EPOCH', default=100, type=int)
parser.add_argument('--Min_train_performance_Report', default=0, type=int)
parser.add_argument('--EARLY_STOP_NUM', default=20, type=int)

parser.add_argument('--LR_max_bert', default=1e-5, type=float)
parser.add_argument('--LR_min_bert', default=1e-6, type=float)
parser.add_argument('--LR_max_entity_span', default=1e-4, type=float)
parser.add_argument('--LR_min_entity_span', default=2e-6, type=float)
parser.add_argument('--LR_max_entity_type', default=2e-5, type=float)
parser.add_argument('--LR_min_entity_type', default=2e-6, type=float)
parser.add_argument('--LR_max_entity_span_and_type', default=2e-5, type=float)
parser.add_argument('--LR_min_entity_span_and_type', default=2e-6, type=float)
parser.add_argument('--LR_max_relation', default=1e-4, type=float)
parser.add_argument('--LR_min_relation', default=5e-6, type=float)
parser.add_argument('--L2', default=1e-2, type=float)

parser.add_argument('--Weight_Loss', action='store_true', default=True)
parser.add_argument('--Loss', type=str, default="BCE", help=["BCE", "CE", "FSL"])
parser.add_argument('--Min_weight', default=0.5, type=float)
parser.add_argument('--Max_weight', default=5, type=float)
parser.add_argument('--Tau', default=1.0, type=float)
parser.add_argument('--Type_emb_num', default=50, type=int)

parser.add_argument('--Relation_input', default="entity_span", type=str, help=["entity_span", "entity_span_and_type"])
parser.add_argument('--Only_relation', action='store_true', default=False)
parser.add_argument('--Num_warmup_epoch', default=3, type=int)
parser.add_argument('--Tensorboard', action='store_true', default=True)
parser.add_argument('--Optim', default="AdamW", type=str, help=["AdamW"])
parser.add_argument('--ID', default=0, type=int, help="Just for tensorboard reg")

parser.add_argument('--IF_CRF', action='store_true', default=False)
parser.add_argument('--Decay_epoch_num', default=40, type=float)
parser.add_argument('--Improve_Flag', action='store_true', default=False)
# AdamW  --LR_bert=5e-4 --LR_classfier=1e-3  70.285
args = parser.parse_args()

os.environ["CUDA_VISIBLE_DEVICES"] = args.GPU
warnings.filterwarnings("ignore")

file_param_record = '../result/param_record'
file_detail_performance = '../result/detail_performance/performance_' + str(sys.argv[1:]) + '.txt'
file_result = '../result/detail_results/result_' + str(sys.argv[1:]) + '.json'
file_model_save = "../result/save_model/" +"Model_"+ str(sys.argv[1:])
file_traning_performerance = '../result/detail_training/training_' + str(sys.argv[1:]) + '.txt'

sys.stdout = Logger(filename=file_traning_performerance)
tensor_board_path = '../result/runs/'+str(sys.argv[1:])
try: shutil.rmtree(tensor_board_path)
except FileNotFoundError: pass

args.Task_weights_dic=eval(args.Task_weights_dic)
v_sum = 0
for k,v in args.Task_weights_dic.items():
    if k in args.Task_list:
        v_sum+=v
assert v_sum==1

if args.Test_TAC_flag and (not args.Inner_test_TAC_flag):
    args.Group_num=1

if args.Test_TAC_flag:
    assert args.Test_flag

if args.Inner_test_TAC_flag:
    assert args.Test_flag
    assert args.Test_TAC_flag
    args.Min_train_performance_Report = 0
    args.Average_Time = 1

# if args.Test_TAC_flag :
#     if not args.Test_flag:
#         raise Exception("Test_TAC_flag and Test_flag must compatoble")

if args.bert_model == "large":
    args.model_path = "../../../Data/embedding/biobert_large"
    args.Word_embedding_size = 1024
    args.Hidden_Size_Common_Encoder = args.Word_embedding_size
elif args.bert_model == "base":
    args.model_path = "../../../Data/embedding/biobert_base"
    args.Word_embedding_size = 768
    args.Hidden_Size_Common_Encoder = args.Word_embedding_size

from torch.utils.tensorboard import SummaryWriter
import torch
import transformers
import torch.optim as optim

# device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
torch.backends.cudnn.benchmark = True
device = torch.device("cuda")
OPTIMIZER = eval("optim." + args.Optim)
Embedding_requires_grad = True
BATCH_FIRST = True
SEED = 1234
torch.manual_seed(SEED)
torch.cuda.manual_seed(SEED)


class Train_valid_test():
    def __init__(self, data_ID_2_corpus_dic, my_model, tokenizer_list,
                 train_iterator_list, valid_iterator_list, test_iterator_list,
                 sep_corpus_file_dic, ema, writer):

        self.my_model = my_model.to(device)
        self.current_epoch = 0
        self.tokenizer_list = tokenizer_list

        self.data_ID_2_corpus_dic = data_ID_2_corpus_dic

        if args.Training_way == "Multi_Task_continual_Training":
            self.train_iterator_dic = self.get_dic_data(train_iterator_list, args.Group_num, "train")
            self.valid_iterator_dic = self.get_dic_data(valid_iterator_list, args.Group_num, "valid")
            self.test_iterator_dic = self.get_dic_data(test_iterator_list, 1, "test")
        elif args.Training_way == "Multi_Task_Training":
            self.train_iterator_dic = train_iterator_list
            self.valid_iterator_dic = valid_iterator_list
            self.test_iterator_dic = test_iterator_list
        else:
            raise Exception("Training_way error")

        self.writer = writer
        self.ema = ema
        num_warmup_step = args.Num_warmup_epoch * len(train_iterator_list[0])
        num_training_steps = args.Decay_epoch_num * len(train_iterator_list[0])

        self.sep_corpus_file_dic = sep_corpus_file_dic
        self.all_entity_type_classifier_list = ["only_entity_type_"+i for i in ['Gene', 'Drug', 'Disease']]
        self.all_entity_span_and_type_classifier_list = ["joint_entity_type_"+i for i in ['Gene', 'Drug', 'Disease']]
        self.all_relation_classifier_list = ["relation_"+i for i in ['Drug_Disease_interaction', 'Drug_Gene_interaction', 'Drug_Drug_interaction']]
        self.flase_flag = False


        self.optimizer_bert_NER = OPTIMIZER(params=filter(lambda p: p.requires_grad, self.my_model.bert_NER.parameters()), lr=args.LR_max_bert, weight_decay=args.L2)
        self.scheduler_bert_NER = transformers.get_constant_schedule_with_warmup(self.optimizer_bert_NER, num_warmup_step)
        if "relation" in args.Task_list:
            self.optimizer_bert_RC = OPTIMIZER(params=filter(lambda p: p.requires_grad, self.my_model.bert_RC.parameters()), lr=args.LR_max_bert, weight_decay=args.L2)
            self.scheduler_bert_RC = transformers.get_constant_schedule_with_warmup(self.optimizer_bert_RC, num_warmup_step)

        for task in self.my_model.task_list:
            # set tasks optim
            my_parameters = getattr(self.my_model, "my_"+task+"_classifier").parameters()
            my_lr_min = getattr(args, "LR_min_" + str(task))
            my_lr_max = getattr(args, "LR_max_" + str(task))
            setattr(self, "optimizer_"+str(task), OPTIMIZER(params=filter(lambda p: p.requires_grad, my_parameters),
                                                            lr=my_lr_max, weight_decay=args.L2))
            # set tasks scheduler
            my_optim = getattr(self, "optimizer_"+str(task))
            setattr(self, "scheduler_" + str(task), transformers.get_constant_schedule_with_warmup(my_optim, num_warmup_step))

        if args.If_add_prototype:
            self.entity_type_rep_dic = get_entity_type_rep_dic(train_iterator_list, valid_iterator_list, self.my_model, args.Type_emb_num, device)
        else:
            self.entity_type_rep_dic = {}

    def sep_list(self, listTemp, n):
        step = math.ceil(len(listTemp)/n)
        return_list = []
        s_index = 0
        e_index = 0
        for i in range(n):
            e_index += step
            return_list.append(listTemp[s_index: e_index])
            s_index = e_index
        return return_list

    def get_dic_data(self, iterator_list, group_num, data_flag):
        # no stage, only group (group=1 = one-by-one)
        NER_data_dic = {}
        RC_data_dic = {}
        return_data_dic = {}
        NER_total_list = [batch for batch in iterator_list[0]]
        RC_total_list = [batch for batch in iterator_list[1]]

        if args.Test_TAC_flag and (not args.Inner_test_TAC_flag) and (data_flag=="train" or data_flag=="valid"):
            return return_data_dic
        else:
            corpus_list = copy.deepcopy(args.Corpus_list)

            if data_flag=="train" or data_flag=="valid":
                if "TAC2019" in corpus_list:
                    corpus_list.remove("TAC2019")

            if data_flag=="test" and args.Test_TAC_flag:
                corpus_list = ["TAC2019"]

            for NER_batch in NER_total_list:
                corpus_name = self.data_ID_2_corpus_dic[str(int(NER_batch.ID[0]))[:5]]
                NER_data_dic.setdefault(corpus_name, [])
                NER_data_dic[corpus_name].append(NER_batch)

            for RC_batch in RC_total_list:
                corpus_name = self.data_ID_2_corpus_dic[str(int(RC_batch.ID[0]))[:5]]
                RC_data_dic.setdefault(corpus_name, [])
                RC_data_dic[corpus_name].append(RC_batch)

            for corpus_name in corpus_list:
                NER_group = [NER_data_dic[corpus_name]]
                RC_group = [RC_data_dic[corpus_name]]
                return_data_dic[corpus_name] = [[ner_data, rc_data] for ner_data, rc_data in zip(NER_group, RC_group)]

            if args.Test_TAC_flag and data_flag=="test":
                new_return_data_dic = {}
                new_return_data_dic["TAC2019"] = return_data_dic["TAC2019"]
                return_data_dic = new_return_data_dic

        new_return_data_dic = {0: {}}
        for stage, dic_group in new_return_data_dic.items():
            for corpus in corpus_list:
                if stage < len(return_data_dic[corpus]):
                    NER_temp_list = self.sep_list(return_data_dic[corpus][stage][0], group_num)
                    RC_temp_list = self.sep_list(return_data_dic[corpus][stage][1], group_num)
                    for group in range(group_num):
                        new_return_data_dic[stage].setdefault(group, {})
                        new_return_data_dic[stage][group][corpus] = [NER_temp_list[group], RC_temp_list[group]]
        return new_return_data_dic

    def save_model(self, epoch):
        self.model_state_dic = {}
        self.model_state_dic['epoch'] = epoch
        self.model_state_dic['entity_type_rep_dic'] = self.entity_type_rep_dic
        self.model_state_dic['my_model'] = self.my_model.state_dict()
        torch.save(self.model_state_dic, file_model_save)

    def one_epoch(self, iterator_dic, valid_test_flag, epoch):
        """
        dic_batches_res = {"entity_span":[  batch-num [ ( one_batch_pred_sub_res[batch_size[entity_num]], [batch.entity_span] ) ] ],
                            "entity_type":[], "relation":[]}
        """
        dic_batches_res = {"ID_list":[], "tokens_list":[], "corpus_name_list":[], "entity_span":[], "entity_type":[], "entity_span_and_type":[], "relation":[]}
        epoch_entity_span_loss = 0
        epoch_entity_type_loss = 0
        epoch_entity_span_and_type_loss = 0
        epoch_relation_loss = 0
        count = 0

        corpus_list = copy.deepcopy(args.Corpus_list)
        if "TAC2019" in corpus_list:
            corpus_list.remove("TAC2019")

        if args.Training_way == "Multi_Task_continual_Training":
            for stage_number in reversed(range(len(iterator_dic))):
                for group_number in range(args.Group_num):
                    for corpus_name in corpus_list:
                        entity_type_no_need_list = []
                        entity_span_and_type_no_need_list = []
                        relation_no_need_list = []

                        if corpus_name in iterator_dic[stage_number][group_number].keys():

                            if valid_test_flag=="train":
                                if args.Random_ratio >= np.random.uniform(0,1):
                                    self.flase_flag = True
                                    if "entity_type" in args.Task_list:
                                        for class_name in list(set(self.all_entity_type_classifier_list).difference(set(self.sep_corpus_file_dic[corpus_name]['entity_type'])))  :
                                            if hasattr(self.my_model.my_entity_type_classifier, "my_classifer_{0}".format(class_name)):
                                                no_need_classifer = getattr(self.my_model.my_entity_type_classifier, "my_classifer_{0}".format(class_name))
                                                entity_type_no_need_list.append(no_need_classifer)
                                                for p in no_need_classifer.parameters():
                                                    p.requires_grad = False
                                    if "entity_span_and_type" in args.Task_list:
                                        for class_name in list(set(self.all_entity_span_and_type_classifier_list).difference(set(self.sep_corpus_file_dic[corpus_name]['entity_span_and_type'])))  :
                                            if hasattr(self.my_model.my_entity_span_and_type_classifier, "my_classifer_{0}".format(class_name)):
                                                no_need_classifer = getattr(self.my_model.my_entity_span_and_type_classifier, "my_classifer_{0}".format(class_name))
                                                entity_span_and_type_no_need_list.append(no_need_classifer)
                                                for p in no_need_classifer.parameters():
                                                    p.requires_grad = False
                                    if "relation" in args.Task_list:
                                        for class_name in list(set(self.all_relation_classifier_list).difference(set(self.sep_corpus_file_dic[corpus_name]['relation'])))  :
                                            if hasattr(self.my_model.my_relation_classifier, "my_classifer_{0}".format(class_name)):
                                                no_need_classifer = getattr(self.my_model.my_relation_classifier, "my_classifer_{0}".format(class_name))
                                                relation_no_need_list.append(no_need_classifer)
                                                for p in no_need_classifer.parameters():
                                                    p.requires_grad = False

                            group_list_NER_RC = iterator_dic[stage_number][group_number][corpus_name]

                            if "relation" in args.Task_list:
                                temp_my_iterator_list = [ [ner, rc] for ner, rc in zip(group_list_NER_RC[0], group_list_NER_RC[1]) ]
                            else:
                                raise Exception("error!")

                            for batch_list in temp_my_iterator_list:
                                count+=1
                                with torch.cuda.amp.autocast():
                                    dic_loss_one_batch, dic_res_one_batch = self.my_model.forward(batch_list, epoch, self.entity_type_rep_dic, valid_test_flag)

                                batch_loss_list = []
                                if "entity_span" in self.my_model.task_list:
                                    # batch_entity_span_loss = args.Task_weights_dic["entity_span"] * dic_loss_one_batch["entity_span"]
                                    batch_entity_span_loss = dic_loss_one_batch["entity_span"]
                                    epoch_entity_span_loss += batch_entity_span_loss
                                    batch_loss_list.append(batch_entity_span_loss)
                                if "entity_type" in self.my_model.task_list and dic_loss_one_batch["entity_type"] != None:
                                    # batch_entity_type_loss =  args.Task_weights_dic["entity_type"] * dic_loss_one_batch["entity_type"]
                                    batch_entity_type_loss =   dic_loss_one_batch["entity_type"]
                                    epoch_entity_type_loss += batch_entity_type_loss
                                    batch_loss_list.append(batch_entity_type_loss)
                                if "entity_span_and_type" in self.my_model.task_list:
                                    # batch_entity_span_and_type_loss = args.Task_weights_dic["entity_span_and_type"] * dic_loss_one_batch["entity_span_and_type"]
                                    batch_entity_span_and_type_loss =  dic_loss_one_batch["entity_span_and_type"]
                                    epoch_entity_span_and_type_loss += batch_entity_span_and_type_loss
                                    batch_loss_list.append(batch_entity_span_and_type_loss)
                                if "relation" in self.my_model.task_list:
                                    # batch_relation_loss = args.Task_weights_dic["relation"] * dic_loss_one_batch["relation"]
                                    batch_relation_loss =  dic_loss_one_batch["relation"]
                                    epoch_relation_loss += batch_relation_loss
                                    batch_loss_list.append(batch_relation_loss)

                                if valid_test_flag=="train":

                                    batch_loss = torch.dot(torch.tensor(list(args.Task_weights_dic.values()), device=device), torch.stack(batch_loss_list))

                                    batch_loss.backward()
                                    self.scheduler_bert_NER.step()
                                    self.optimizer_bert_NER.step()
                                    self.optimizer_bert_NER.zero_grad()

                                    if "relation" in args.Task_list:
                                        self.scheduler_bert_RC.step()
                                        self.optimizer_bert_RC.step()
                                        self.optimizer_bert_RC.zero_grad()

                                    for task in self.my_model.task_list:
                                        getattr(self, "scheduler_"+str(task)).step()
                                        getattr(self, "optimizer_"+str(task)).step()
                                        getattr(self, "optimizer_"+str(task)).zero_grad()
                                    self.ema.update()

                                dic_batches_res["ID_list"].append(batch_list[0].ID)
                                dic_batches_res["tokens_list"].append(batch_list[0].tokens)
                                dic_batches_res["corpus_name_list"].append(corpus_name)
                                for task in self.my_model.task_list:
                                    try:
                                        dic_batches_res[task].append(dic_res_one_batch[task])
                                    except:
                                        pass #nothing wrong

                            if valid_test_flag=="train" and self.flase_flag:
                                if "entity_type" in args.Task_list:
                                    for class_name in entity_type_no_need_list  :
                                        for p in class_name.parameters():
                                            p.requires_grad = True
                                if "entity_span_and_type" in args.Task_list:
                                    for class_name in entity_span_and_type_no_need_list:
                                        for p in class_name.parameters():
                                            p.requires_grad = True
                                if "relation" in args.Task_list:
                                    for class_name in relation_no_need_list:
                                        for p in class_name.parameters():
                                            p.requires_grad = True
        elif args.Training_way == "Multi_Task_Training":

            if "relation" in args.Task_list:
                temp_my_iterator_list = [ [ner, rc] for ner, rc in zip(iterator_dic[0], iterator_dic[1]) ]
            else:
                raise Exception("error!")

            for batch_list in temp_my_iterator_list:
                count+=1
                with torch.cuda.amp.autocast():
                    dic_loss_one_batch, dic_res_one_batch = self.my_model.forward(batch_list, epoch, self.entity_type_rep_dic, valid_test_flag)

                batch_loss_list = []
                if "entity_span" in self.my_model.task_list:
                    # batch_entity_span_loss = args.Task_weights_dic["entity_span"] * dic_loss_one_batch["entity_span"]
                    batch_entity_span_loss = dic_loss_one_batch["entity_span"]
                    epoch_entity_span_loss += batch_entity_span_loss
                    batch_loss_list.append(batch_entity_span_loss)
                if "entity_type" in self.my_model.task_list and dic_loss_one_batch["entity_type"] != None:
                    # batch_entity_type_loss =  args.Task_weights_dic["entity_type"] * dic_loss_one_batch["entity_type"]
                    batch_entity_type_loss =   dic_loss_one_batch["entity_type"]
                    epoch_entity_type_loss += batch_entity_type_loss
                    batch_loss_list.append(batch_entity_type_loss)
                if "entity_span_and_type" in self.my_model.task_list:
                    # batch_entity_span_and_type_loss = args.Task_weights_dic["entity_span_and_type"] * dic_loss_one_batch["entity_span_and_type"]
                    batch_entity_span_and_type_loss =  dic_loss_one_batch["entity_span_and_type"]
                    epoch_entity_span_and_type_loss += batch_entity_span_and_type_loss
                    batch_loss_list.append(batch_entity_span_and_type_loss)
                if "relation" in self.my_model.task_list:
                    # batch_relation_loss = args.Task_weights_dic["relation"] * dic_loss_one_batch["relation"]
                    batch_relation_loss =  dic_loss_one_batch["relation"]
                    epoch_relation_loss += batch_relation_loss
                    batch_loss_list.append(batch_relation_loss)

                if valid_test_flag=="train":

                    batch_loss = torch.dot(torch.tensor(list(args.Task_weights_dic.values()), device=device), torch.stack(batch_loss_list))

                    batch_loss.backward()
                    self.scheduler_bert_NER.step()
                    self.optimizer_bert_NER.step()
                    self.optimizer_bert_NER.zero_grad()

                    if "relation" in args.Task_list:
                        self.scheduler_bert_RC.step()
                        self.optimizer_bert_RC.step()
                        self.optimizer_bert_RC.zero_grad()

                    for task in self.my_model.task_list:
                        getattr(self, "scheduler_"+str(task)).step()
                        getattr(self, "optimizer_"+str(task)).step()
                        getattr(self, "optimizer_"+str(task)).zero_grad()
                    self.ema.update()

                dic_batches_res["ID_list"].append(batch_list[0].ID)
                dic_batches_res["tokens_list"].append(batch_list[0].tokens)
                # dic_batches_res["corpus_name_list"].append(corpus_name)
                for task in self.my_model.task_list:
                    try:
                        dic_batches_res[task].append(dic_res_one_batch[task])
                    except:
                        pass #nothing wrong
        else:
            raise Exception("Training_way error !")

        epoch_loss = 0
        dic_loss = {"average":0 }
        if "entity_span" in self.my_model.task_list:
            dic_loss["entity_span"] = epoch_entity_span_loss/ count
            epoch_loss += epoch_entity_span_loss/ count
        if "entity_type" in self.my_model.task_list:
            dic_loss["entity_type"] = epoch_entity_type_loss/ count
            epoch_loss += epoch_entity_type_loss/ count
        if "entity_span_and_type" in self.my_model.task_list:
            dic_loss["entity_span_and_type"] = epoch_entity_span_and_type_loss/ count
            epoch_loss += epoch_entity_span_and_type_loss/ count
        if "relation" in self.my_model.task_list:
            dic_loss["relation"] = epoch_relation_loss/ count
            epoch_loss += epoch_relation_loss/ count

        dic_loss["average"] = epoch_loss / len(self.my_model.task_list)

        return dic_loss, dic_batches_res

    def one_epoch_train(self, epoch):
        self.my_model.train()
        dic_loss, dic_batches_res= self.one_epoch(self.train_iterator_dic, "train", epoch)
        return dic_loss, dic_batches_res

    def one_epoch_valid(self, epoch):
        with torch.no_grad():
            self.my_model.eval()
            self.ema.apply_shadow()
            dic_loss, dic_batches_res = self.one_epoch(self.valid_iterator_dic, "valid", epoch)
            self.ema.restore()
        # torch.cuda.empty_cache()
        return dic_loss, dic_batches_res

    @print_execute_time
    def train_valid_fn(self, average_num):
        save_epoch = 0
        early_stop_num = args.EARLY_STOP_NUM
        maxF = 0

        corpus_list = copy.deepcopy(args.Corpus_list)
        if "TAC2019" in corpus_list and not args.Inner_test_TAC_flag:
            corpus_list.remove("TAC2019")

        print("start training...")
        for epoch in range(self.current_epoch, args.EPOCH+1):

            dic_train_loss, dic_batches_train_res = self.one_epoch_train(epoch)
            if epoch >= args.Min_train_performance_Report :
                dic_train_PRF, dic_total_sub_task_P_R_F, dic_corpus_task_micro_P_R_F, dic_TP_FN_FP \
                    = report_performance(epoch, self.my_model.task_list, dic_train_loss, dic_batches_train_res,
                                         self.my_model.classifiers_dic,
                                         self.sep_corpus_file_dic,
                                         args.Improve_Flag, "train")

                if args.Tensorboard:
                    for task in self.my_model.task_list:
                        self.writer.add_scalars("Performance_P/"+task, {"train":dic_train_PRF[task][0]}, epoch)
                        self.writer.add_scalars("Performance_R/"+task, {"train":dic_train_PRF[task][1]}, epoch)
                        self.writer.add_scalars("Performance_F/"+task, {"train":dic_train_PRF[task][2]}, epoch)
                        self.writer.add_scalars("Loss/"+task, {"train":dic_train_loss[task]}, epoch)
                        self.writer.add_scalars("Learning rate/"+task, {task: getattr(self, "optimizer_"+str(task)).param_groups[0]["lr"]}, epoch)
                    self.writer.add_scalars("Learning rate/bert_encoder_RC", {"bert_encoder_RC": self.optimizer_bert_RC.param_groups[0]["lr"]}, epoch)

                    # log_gradient_updates(self.writer, self.my_model, epoch)
                    # log_parameter_and_gradient_statistics(self.my_model, self.writer, epoch)
                    # self.writer.close()

                if args.Inner_test_TAC_flag:
                    print("test TAC...", end="")
                    dic_valid_PRF, dic_valid_total_sub_task_P_R_F, dic_valid_corpus_task_micro_P_R_F, dic_valid_TP_FN_FP = self.test_fn(args.Test_model_file)
                else:
                    dic_valid_loss, dic_batches_valid_res = self.one_epoch_valid(epoch)

                    dic_valid_PRF, dic_valid_total_sub_task_P_R_F, dic_valid_corpus_task_micro_P_R_F, dic_valid_TP_FN_FP \
                        = report_performance(epoch, self.my_model.task_list, dic_valid_loss, dic_batches_valid_res,
                                             self.my_model.classifiers_dic,
                                             self.sep_corpus_file_dic,
                                             args.Improve_Flag, "valid")
                    if args.Tensorboard:
                        for task in self.my_model.task_list:
                            self.writer.add_scalars("Performance_P/"+task, {"valid":dic_valid_PRF[task][0]}, epoch)
                            self.writer.add_scalars("Performance_R/"+task, {"valid":dic_valid_PRF[task][1]}, epoch)
                            self.writer.add_scalars("Performance_F/"+task, {"valid":dic_valid_PRF[task][2]}, epoch)
                            self.writer.add_scalars("Loss/"+task, {"valid":dic_valid_loss[task]}, epoch)
                        self.writer.close()

                if dic_valid_PRF[args.Task_list[-1]][2] >= maxF:
                    early_stop_num = args.EARLY_STOP_NUM
                    maxF = dic_valid_PRF[args.Task_list[-1]][2]
                    recored_best_dic = dic_valid_PRF
                    save_epoch = epoch
                    # self.save_model(save_epoch)

                    # record_pred_str_res(self.my_model.task_list, file_result, dic_batches_valid_res, average_num,
                    #                     self.tokenizer_list[0].convert_ids_to_tokens, self.my_model.classifiers_dic,
                    #                     args.IF_CRF)

                    recored_detail_performance(epoch, dic_valid_total_sub_task_P_R_F, dic_valid_PRF, file_detail_performance,
                                               dic_valid_corpus_task_micro_P_R_F, dic_valid_TP_FN_FP,
                                               self.sep_corpus_file_dic, args.Task_list, corpus_list, args.Average_Time)
                else :
                    early_stop_num -= 1

                if early_stop_num <= 0:
                    print()
                    print("early stop, in epoch: %d !" % (int(save_epoch)))
                    for task in args.Task_list:
                        print(task, ": max F: %s, " % (str(recored_best_dic[task][-1])))
                    return recored_best_dic

            else:
                print("epoch: ", epoch)
        print()
        print("Reach max epoch: %d !" % (int(save_epoch)))

        for task in args.Task_list:
            print(task, ": max F: %s, " % (str(recored_best_dic[task][-1])))
        # self.save_model(save_epoch)
        return recored_best_dic

    def test_fn(self, file_model_save):

        if not args.Inner_test_TAC_flag:
            print(file_model_save)
            print("Loading Model...")
            checkpoint = torch.load(file_model_save)
            self.my_model.load_state_dict(checkpoint['my_model'])
            self.entity_type_rep_dic = checkpoint['epoch']
            print("Loading success !")

        if args.Test_TAC_flag:
            corpus_list = ["TAC2019"]
        else:
            corpus_list = args.Corpus_list

        with torch.no_grad():
            self.my_model.eval()
            dic_batches_res = {"ID_list":[], "tokens_list":[], "entity_span":[], "entity_type":[], "entity_span_and_type":[], "relation":[]}
            epoch_entity_span_loss = 0
            epoch_entity_type_loss = 0
            epoch_entity_span_and_type_loss = 0
            epoch_relation_loss = 0
            count = 0
            group_num=1

            if args.Training_way == "Multi_Task_continual_Training":
                for group_number in range(group_num):
                    for corpus_name in corpus_list:
                        group_list_NER_RC = self.test_iterator_dic[0][group_number][corpus_name]
                        if "relation" in args.Task_list:
                            temp_my_iterator_list = [ [ner, rc] for ner, rc in zip(group_list_NER_RC[0], group_list_NER_RC[1]) ]
                        else:
                            # only relation have a bug
                            temp_my_iterator_list = [ [i] for i in group_list_NER_RC[0]]

                        for batch_list in temp_my_iterator_list:
                            count+=1
                            with torch.cuda.amp.autocast():
                                dic_loss_one_batch, dic_res_one_batch = self.my_model.forward(batch_list, 0, self.entity_type_rep_dic, "valid")
                                batch_loss_list = []
                                if "entity_span" in self.my_model.task_list:
                                    batch_entity_span_loss = args.Task_weights_dic["entity_span"] * dic_loss_one_batch["entity_span"]
                                    epoch_entity_span_loss += batch_entity_span_loss
                                    batch_loss_list.append(batch_entity_span_loss)
                                if "entity_type" in self.my_model.task_list and dic_loss_one_batch["entity_type"] != None:
                                    batch_entity_type_loss =  args.Task_weights_dic["entity_type"] * dic_loss_one_batch["entity_type"]
                                    epoch_entity_type_loss += batch_entity_type_loss
                                    batch_loss_list.append(batch_entity_type_loss)
                                if "entity_span_and_type" in self.my_model.task_list:
                                    batch_entity_span_and_type_loss = args.Task_weights_dic["entity_span_and_type"] * dic_loss_one_batch["entity_span_and_type"]
                                    epoch_entity_span_and_type_loss += batch_entity_span_and_type_loss
                                    batch_loss_list.append(batch_entity_span_and_type_loss)
                                if "relation" in self.my_model.task_list:
                                    batch_relation_loss = args.Task_weights_dic["relation"] * dic_loss_one_batch["relation"]
                                    epoch_relation_loss += batch_relation_loss
                                    batch_loss_list.append(batch_relation_loss)

                                dic_batches_res["ID_list"].append(batch_list[0].ID)
                                dic_batches_res["tokens_list"].append(batch_list[0].tokens)
                                for task in self.my_model.task_list:
                                    try:
                                        dic_batches_res[task].append(dic_res_one_batch[task])
                                    except:
                                        pass
            elif args.Training_way == "Multi_Task_Training":

                if "relation" in args.Task_list:
                    temp_my_iterator_list = [ [ner, rc] for ner, rc in zip(self.test_iterator_dic[0], self.test_iterator_dic[1]) ]
                else:
                    raise Exception("error!")

                for batch_list in temp_my_iterator_list:
                    count+=1
                    with torch.cuda.amp.autocast():
                        dic_loss_one_batch, dic_res_one_batch = self.my_model.forward(batch_list, 0, self.entity_type_rep_dic, "valid")

                    batch_loss_list = []
                    if "entity_span" in self.my_model.task_list:
                        # batch_entity_span_loss = args.Task_weights_dic["entity_span"] * dic_loss_one_batch["entity_span"]
                        batch_entity_span_loss = dic_loss_one_batch["entity_span"]
                        epoch_entity_span_loss += batch_entity_span_loss
                        batch_loss_list.append(batch_entity_span_loss)
                    if "entity_type" in self.my_model.task_list and dic_loss_one_batch["entity_type"] != None:
                        # batch_entity_type_loss =  args.Task_weights_dic["entity_type"] * dic_loss_one_batch["entity_type"]
                        batch_entity_type_loss =   dic_loss_one_batch["entity_type"]
                        epoch_entity_type_loss += batch_entity_type_loss
                        batch_loss_list.append(batch_entity_type_loss)
                    if "entity_span_and_type" in self.my_model.task_list:
                        # batch_entity_span_and_type_loss = args.Task_weights_dic["entity_span_and_type"] * dic_loss_one_batch["entity_span_and_type"]
                        batch_entity_span_and_type_loss =  dic_loss_one_batch["entity_span_and_type"]
                        epoch_entity_span_and_type_loss += batch_entity_span_and_type_loss
                        batch_loss_list.append(batch_entity_span_and_type_loss)
                    if "relation" in self.my_model.task_list:
                        # batch_relation_loss = args.Task_weights_dic["relation"] * dic_loss_one_batch["relation"]
                        batch_relation_loss =  dic_loss_one_batch["relation"]
                        epoch_relation_loss += batch_relation_loss
                        batch_loss_list.append(batch_relation_loss)

                    dic_batches_res["ID_list"].append(batch_list[0].ID)
                    dic_batches_res["tokens_list"].append(batch_list[0].tokens)
                    for task in self.my_model.task_list:
                        try:
                            dic_batches_res[task].append(dic_res_one_batch[task])
                        except:
                            pass #nothing wrong
            else:
                raise Exception("Training_way error !")


            epoch_loss = 0
            dic_loss = {"average":0 }
            if "entity_span" in self.my_model.task_list:
                dic_loss["entity_span"] = epoch_entity_span_loss/ count
                epoch_loss += epoch_entity_span_loss/ count
            if "entity_type" in self.my_model.task_list:
                dic_loss["entity_type"] = epoch_entity_type_loss/ count
                epoch_loss += epoch_entity_type_loss/ count
            if "entity_span_and_type" in self.my_model.task_list:
                dic_loss["entity_span_and_type"] = epoch_entity_span_and_type_loss/ count
                epoch_loss += epoch_entity_span_and_type_loss/ count
            if "relation" in self.my_model.task_list:
                dic_loss["relation"] = epoch_relation_loss/ count
                epoch_loss += epoch_relation_loss/ count

            dic_loss["average"] = epoch_loss / len(self.my_model.task_list)

            dic_test_PRF, dic_total_sub_task_P_R_F, dic_corpus_task_micro_P_R_F, dic_TP_FN_FP \
                = report_performance(0, self.my_model.task_list, dic_loss, dic_batches_res,
                                     self.my_model.classifiers_dic,
                                     self.sep_corpus_file_dic,
                                     args.Improve_Flag, "train")

            if not args.Inner_test_TAC_flag:
                recored_detail_performance(0, dic_total_sub_task_P_R_F, dic_test_PRF, file_detail_performance.replace('.txt', "_TAC.txt"),
                                           dic_corpus_task_micro_P_R_F, dic_TP_FN_FP,
                                           self.sep_corpus_file_dic, args.Task_list, corpus_list, args.Average_Time)

        return dic_test_PRF, dic_total_sub_task_P_R_F, dic_corpus_task_micro_P_R_F, dic_TP_FN_FP

@print_execute_time
def get_valid_performance(model_path):
    writer = SummaryWriter(tensor_board_path)
    corpus_file_dic, sep_corpus_file_dic, pick_corpus_file_dic, combining_data_files_list, entity_type_list, relation_list \
        = get_corpus_file_dic(args.All_data, args.Corpus_list, args.Task_list, args.bert_model, args.Test_TAC_flag)

    make_model_data(args.bert_model, pick_corpus_file_dic, combining_data_files_list, entity_type_list, relation_list, args.All_data)
    data_ID_2_corpus_dic = {"44444":"ADE", "11111":"CPR",  "22222":"DDI", "33333":"Twi_ADE", "55555":"TAC2019"}

    bert_NER = transformers.BertModel.from_pretrained(model_path)
    tokenizer_NER = transformers.BertTokenizer.from_pretrained(model_path)

    bert_RC = transformers.BertModel.from_pretrained(model_path, is_decoder=args.If_soft_share, add_cross_attention=args.If_soft_share)
    tokenizer_RC = transformers.BertTokenizer.from_pretrained(model_path)

    entitiy_type_list = ["Drug", "Gene", "Disease"]
    ADDITIONAL_SPECIAL_TOKENS_start = ["[Entity_only_entity_type_"+i+"]" for i in entitiy_type_list]
    ADDITIONAL_SPECIAL_TOKENS_end = ["[/Entity_only_entity_type_"+i+"]" for i in entitiy_type_list]
    ADDITIONAL_SPECIAL_TOKENS = ADDITIONAL_SPECIAL_TOKENS_start + ADDITIONAL_SPECIAL_TOKENS_end

    tokenizer_NER.add_special_tokens({"additional_special_tokens": ADDITIONAL_SPECIAL_TOKENS})
    bert_NER.resize_token_embeddings(len(tokenizer_NER))
    tokenizer_RC.add_special_tokens({"additional_special_tokens": ADDITIONAL_SPECIAL_TOKENS})
    bert_RC.resize_token_embeddings(len(tokenizer_RC))

    bert_list = []
    tokenizer_list = []
    bert_NER = My_Bert_Encoder(bert_NER, tokenizer_NER, args, device)
    bert_list.append(bert_NER)
    tokenizer_list.append(tokenizer_NER)

    bert_RC = My_Bert_Encoder(bert_RC, tokenizer_RC, args, device)
    bert_list.append(bert_RC)
    tokenizer_list.append(tokenizer_RC)

    my_model = My_Model(bert_list, args, device).to(device)

    my_entity_span_classifier = My_Entity_Span_Classifier(args, device)
    my_entity_type_classifier = My_Entity_Type_Classifier(args, device)
    my_entity_span_and_type_classifier = My_Entity_Span_And_Type_Classifier(args, device)
    my_relation_classifier = My_Relation_Classifier(args, tokenizer_RC, device)
    classifiers_dic = dict(zip(["entity_span", "entity_type", "entity_span_and_type", "relation"],
                           [my_entity_span_classifier, my_entity_type_classifier, my_entity_span_and_type_classifier, my_relation_classifier]))


    train_iterator_list = []
    valid_iterator_list = []
    test_iterator_list = []


    # for index, (corpus_name, (entity_type_num_list, relation_num_list, file_train_valid_test_list)) in enumerate(corpus_file_dic.items()):
    corpus_name = list(corpus_file_dic.keys())[0]
    entity_type_num_list, relation_num_list, file_train_valid_test_list = corpus_file_dic[corpus_name]
    print("===============" + corpus_name + "===============")

    NER_train_iterator, NER_valid_iterator, NER_test_iterator, NER_TOEKNS_fileds, TAGS_Entity_Span_fileds_dic, \
    TAGS_Entity_Type_fileds_dic, TAGS_Entity_Span_And_Type_fileds_dic, TAGS_sampled_entity_span_fileds_dic, TAGS_sep_entity_fileds_dic \
        = prepared_NER_data(args.BATCH_SIZE, device, tokenizer_NER, file_train_valid_test_list, entity_type_num_list)

    train_iterator_list.append(NER_train_iterator)
    valid_iterator_list.append(NER_test_iterator)
    test_iterator_list.append(NER_test_iterator)

    my_entity_span_classifier.create_classifers(TAGS_Entity_Span_fileds_dic)
    my_entity_type_classifier.create_classifers(TAGS_Entity_Type_fileds_dic, TAGS_sep_entity_fileds_dic)
    my_entity_span_and_type_classifier.create_classifers(TAGS_Entity_Span_And_Type_fileds_dic)

    if "relation" in args.Task_list:
        RC_train_iterator, RC_valid_iterator, RC_test_iterator, RC_TOEKNS_fileds, TAGS_Relation_pair_fileds_dic, TAGS_sampled_entity_span_fileds_dic \
            = prepared_RC_data(args.BATCH_SIZE, device, tokenizer_RC, file_train_valid_test_list, relation_num_list)
        my_relation_classifier.create_classifers(TAGS_Relation_pair_fileds_dic, TAGS_sampled_entity_span_fileds_dic, TAGS_Entity_Type_fileds_dic)

        train_iterator_list.append(RC_train_iterator)
        valid_iterator_list.append(RC_test_iterator)
        test_iterator_list.append(RC_test_iterator)

    my_model.add_classifers(classifiers_dic, args.Task_list)
    ema = EMA(my_model, 0.999, device)
    ema.register()

    my_train_valid_test = Train_valid_test(data_ID_2_corpus_dic, my_model, tokenizer_list,
                                           train_iterator_list, valid_iterator_list, test_iterator_list,
                                           sep_corpus_file_dic, ema, writer)
    Average_Time_list = []
    for i in range(args.Average_Time):
        print("==========================" + str(i) + "=================================================")
        if not args.Test_flag:
            dic_res_PRF = my_train_valid_test.train_valid_fn(i)
        elif args.Test_flag and args.Inner_test_TAC_flag:
            dic_res_PRF = my_train_valid_test.train_valid_fn(i)
        elif args.Test_flag and not args.Inner_test_TAC_flag:
            dic_res_PRF = my_train_valid_test.test_fn(args.Test_model_file)
        else:
            raise Exception("test choose error !")
        Average_Time_list.append(dic_res_PRF)  # inceasing train cause wrong there !!

    record_each_performance(file_param_record, args.Task_list, Average_Time_list)


if __name__ == "__main__":

    if args.Entity_Prep_Way !="standard":
        print("warning, Entity_Prep_Way is not default : ", args.Entity_Prep_Way)
        print()
    if  args.If_add_prototype :
        print("warning, If_add_prototype is not default : ", args.If_add_prototype)
        print()
    if  args.If_soft_share :
        print("warning, If_soft_share is not default : ", args.Entity_Prep_Way)
        print()

    print("GPU:", args.GPU)
    print("Bert:", args.bert_model)
    print("All_data:", args.All_data)
    print("Corpus_list:", args.Corpus_list)
    print("Task_list:", args.Task_list)
    print("Task_weights_dic:", end="")
    for task in args.Task_list:
        print(args.Task_weights_dic[task], end=" ")
    print()
    print("Loss:", args.Loss)
    print("Group_num:", args.Group_num)
    print("EARLY_STOP_NUM:", args.EARLY_STOP_NUM)
    print("Test_flag:", args.Test_flag)
    print("Test_TAC_flag:", args.Test_TAC_flag)
    print("Inner_test_TAC_flag:", args.Inner_test_TAC_flag)
    print("Training_way:", args.Training_way)
    print("Group_num:", args.Group_num)


    # print("Weight_Loss:", args.Weight_Loss)
    # if args.Weight_Loss:
    #     print("Min_weight:", args.Min_weight)
    #     print("Max_weight:", args.Max_weight)
    get_valid_performance(args.model_path)
