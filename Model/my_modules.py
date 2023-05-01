import torch.nn as nn
import torch
import torchtext
from utils import get_sent_len
from itertools import combinations
from torch.nn.utils.rnn import pad_sequence
import torch.nn.functional as F
import copy


class MyEncoder(nn.Module):
    def __init__(self, bert, tokenizer, args, device):
        super(MyEncoder, self).__init__()
        self.to(device)
        self.args = args
        self.device = device
        self.bert = bert
        self.tokenizer = tokenizer
        self.linear_transform = nn.Linear(self.args.Word_embedding_size * 2, self.args.Word_embedding_size)
        self.layer_normalization = nn.LayerNorm([self.args.Word_embedding_size])
        self.output_dim = args.Word_embedding_size

    def forward(self, batch_inputs, ignore_index=0, encoder_hidden_states=None):
        tokens_tensor = self.get_bert_input(batch_inputs)
        attention_mask = self.get_attention_mask(tokens_tensor, ignore_index)
        position_ids = self.get_position_ids(tokens_tensor)
        common_embedding = self.bert(tokens_tensor, output_hidden_states=True, attention_mask=attention_mask,
                                     position_ids=position_ids, encoder_hidden_states=encoder_hidden_states)

        last_common_embedding = common_embedding[0]

        return last_common_embedding

    def get_bert_input(self, batch_inputs):
        input_tensor = torch.tensor(batch_inputs, device=self.device)
        return input_tensor

    def get_attention_mask(self, tokens_tensor, ignore_index):
        attention_mask = torch.where(tokens_tensor == ignore_index, torch.tensor(0., device=self.device),
                                     torch.tensor(1., device=self.device))
        return attention_mask

    def get_position_ids(self, tokens_tensor):
        position_ids = torch.arange(tokens_tensor.shape[1], device=self.device).expand((1, -1))
        return position_ids

    def get_entity_pair_rep(self, entity_pair_span, sentence_embedding):
        entity_span_1, entity_span_2 = entity_pair_span
        entity_1_head = entity_span_1[0]
        entity_1_tail = entity_span_1[-1]
        entity_2_head = entity_span_2[0]
        entity_2_tail = entity_span_2[-1]

        if self.args.Entity_Prep_Way == "entity_type_marker":
            entity_1 = sentence_embedding[entity_1_head]
            entity_2 = sentence_embedding[entity_2_head]
        elif self.args.Entity_Prep_Way == "standard":
            entity_1 = torch.sum(sentence_embedding[entity_1_head:entity_1_tail], dim=0).squeeze()
            entity_2 = torch.sum(sentence_embedding[entity_2_head:entity_2_tail], dim=0).squeeze()
        else:
            raise Exception("args.Entity_Prep_Way error !")

        entity_pair_rep = torch.cat((entity_1, entity_2))
        return entity_pair_rep

    def batch_get_entity_pair_rep(self, batch_tokens, batch_entity, batch_entity_type):
        padding_value = self.tokenizer.vocab['[PAD]']

        if self.args.Entity_Prep_Way == "entity_type_marker":
            raw_batch_entity = copy.deepcopy(batch_entity)
            batch_tokens_marker = []
            for sent_index, (one_sent_tokens, one_sent_entity, one_sent_entity_type) in enumerate(
                    zip(batch_tokens, batch_entity, batch_entity_type)):
                temp_token_list = one_sent_tokens.tolist()
                for entity_index, (span, entity_type) in enumerate(zip(one_sent_entity, one_sent_entity_type)):
                    temp_token_list.insert(span[0],
                                           self.tokenizer.convert_tokens_to_ids("[Entity_" + entity_type + "]"))
                    temp_token_list.insert(span[-1] + 2,
                                           self.tokenizer.convert_tokens_to_ids("[/Entity_" + entity_type + "]"))

                    batch_entity[sent_index][entity_index].insert(0, span[0])
                    batch_entity[sent_index][entity_index].append(span[-1] + 2)

                    # need batch_span is in order in entity list
                    batch_entity[sent_index][entity_index + 1:] = [[j + 2 for j in i] for i in
                                                                   batch_entity[sent_index][entity_index + 1:]]
                    batch_entity[sent_index][entity_index][1:-1] = [i + 1 for i in
                                                                    batch_entity[sent_index][entity_index][1:-1]]
                batch_tokens_marker.append(torch.tensor(temp_token_list, device=self.device))

            common_embedding = self.forward(
                pad_sequence(batch_tokens_marker, batch_first=True, padding_value=padding_value),
                encoder_hidden_states=None)

            batch_entity_pair_span_list = []
            batch_entity_pair_vec_list = []
            batch_sent_len_list = []

            for sent_index, (raw_one_sent_entity, one_sent_entity, one_sent_entity_type) in enumerate(
                    zip(raw_batch_entity, batch_entity, batch_entity_type)):
                sent_entity_pair_span_list = list(combinations(one_sent_entity, 2))
                sent_entity_pair_span_list = [sorted(i) for i in sent_entity_pair_span_list]
                batch_sent_len_list.append(len(sent_entity_pair_span_list))

                raw_sent_entity_pair_span_list = list(combinations(raw_one_sent_entity, 2))
                raw_sent_entity_pair_span_list = [sorted(i) for i in raw_sent_entity_pair_span_list]
                batch_entity_pair_span_list.append(raw_sent_entity_pair_span_list)

                sent_entity_pair_rep_list = []
                if sent_entity_pair_span_list:
                    for entity_pair_span in sent_entity_pair_span_list:
                        one_sent_rep = self.get_entity_pair_rep(entity_pair_span, common_embedding[sent_index])
                        sent_entity_pair_rep_list.append(one_sent_rep)
                else:
                    sent_entity_pair_rep_list.append(
                        torch.tensor([0] * self.output_dim * 2).float().to(self.device))

                batch_entity_pair_vec_list.append(torch.stack(sent_entity_pair_rep_list))

            batch_added_marker_entity_span_vec = pad_sequence(batch_entity_pair_vec_list, batch_first=True,
                                                              padding_value=padding_value)

            batch_added_marker_entity_span_vec = self.linear_transform(batch_added_marker_entity_span_vec)
            batch_added_marker_entity_span_vec = F.gelu(batch_added_marker_entity_span_vec)
            batch_added_marker_entity_span_vec = self.layer_normalization(batch_added_marker_entity_span_vec)

            return batch_added_marker_entity_span_vec, batch_entity_pair_span_list, batch_sent_len_list

        elif self.args.Entity_Prep_Way == "standard":
            common_embedding = self.forward(batch_tokens, encoder_hidden_states=None, ignore_index=padding_value)
            batch_entity_pair_span_list = []
            batch_entity_pair_vec_list = []
            batch_sent_len_list = []

            for sent_index, (one_sent_entity, one_sent_entity_type) in enumerate(zip(batch_entity, batch_entity_type)):
                sent_entity_pair_span_list = list(combinations(one_sent_entity, 2))
                batch_sent_len_list.append(len(sent_entity_pair_span_list))
                sent_entity_pair_span_list = [sorted(i) for i in sent_entity_pair_span_list]

                sent_entity_pair_rep_list = []
                if sent_entity_pair_span_list:
                    for entity_pair_span in sent_entity_pair_span_list:
                        one_sent_rep = self.get_entity_pair_rep(entity_pair_span, common_embedding[sent_index])
                        sent_entity_pair_rep_list.append(one_sent_rep)
                else:
                    sent_entity_pair_rep_list.append(
                        torch.tensor([0] * self.relation_input_dim).float().to(self.device))

                batch_entity_pair_vec_list.append(torch.stack(sent_entity_pair_rep_list))
                batch_entity_pair_span_list.append(sent_entity_pair_span_list)
            batch_added_marker_entity_span_vec = pad_sequence(batch_entity_pair_vec_list, batch_first=True,
                                                              padding_value=padding_value)

            return batch_added_marker_entity_span_vec, batch_entity_pair_span_list, batch_sent_len_list
        else:
            raise Exception("Entity_Prep_Way wrong !")

    def memory_get_entity_pair_rep(self, batch_entity, batch_tokens, batch_entity_type, batch_gold_RE):
        padding_value = self.tokenizer.vocab['[PAD]']

        raw_batch_entity = copy.deepcopy(batch_entity)
        batch_tokens_marker = []
        for sent_index, (one_sent_tokens, one_sent_entity, one_sent_type) in enumerate(
                zip(batch_tokens, batch_entity, batch_entity_type)):
            temp_token_list = one_sent_tokens.tolist()
            for entity_index, (span, entity_type) in enumerate(zip(one_sent_entity, one_sent_type)):
                temp_token_list.insert(span[0], self.tokenizer.convert_tokens_to_ids("[Entity_" + entity_type + "]"))
                temp_token_list.insert(span[-1] + 2,
                                       self.tokenizer.convert_tokens_to_ids("[/Entity_" + entity_type + "]"))

                batch_entity[sent_index][entity_index].insert(0, span[0])
                batch_entity[sent_index][entity_index].append(span[-1] + 2)

                # need batch_span is in order in entity list
                batch_entity[sent_index][entity_index + 1:] = [[j + 2 for j in i] for i in
                                                               batch_entity[sent_index][entity_index + 1:]]
                batch_entity[sent_index][entity_index][1:-1] = [i + 1 for i in
                                                                batch_entity[sent_index][entity_index][1:-1]]
            batch_tokens_marker.append(torch.tensor(temp_token_list, device=self.device))

        common_embedding = self.forward(
            pad_sequence(batch_tokens_marker, batch_first=True, padding_value=padding_value))

        batch_entity_pair_span_list = []
        batch_entity_pair_vec_list = []
        batch_sent_len_list = []

        for sent_index, (raw_one_sent_entity, one_sent_entity, one_sent_type) in enumerate(
                zip(raw_batch_entity, batch_entity, batch_entity_type)):
            temp_sent_entity_pair_span_list = list(combinations(one_sent_entity, 2))
            temp_sent_entity_pair_span_list = [sorted(i) for i in temp_sent_entity_pair_span_list]

            temp_raw_sent_entity_pair_span_list = list(combinations(raw_one_sent_entity, 2))
            temp_raw_sent_entity_pair_span_list = [sorted(i) for i in temp_raw_sent_entity_pair_span_list]

            sent_entity_pair_span_list = []
            raw_sent_entity_pair_span_list = []
            for idx, entity_pair_span in enumerate(temp_raw_sent_entity_pair_span_list):
                if entity_pair_span in batch_gold_RE[sent_index]:
                    sent_entity_pair_span_list.append(temp_sent_entity_pair_span_list[idx])
                    raw_sent_entity_pair_span_list.append(temp_raw_sent_entity_pair_span_list[idx])
            batch_sent_len_list.append(len(sent_entity_pair_span_list))

            batch_entity_pair_span_list.append(raw_sent_entity_pair_span_list)

            sent_entity_pair_rep_list = []
            if sent_entity_pair_span_list:
                for entity_pair_span in sent_entity_pair_span_list:
                    one_sent_rep = self.get_entity_pair_rep(entity_pair_span, common_embedding[sent_index])
                    sent_entity_pair_rep_list.append(one_sent_rep)
            else:
                sent_entity_pair_rep_list.append(
                    torch.tensor([0] * self.output_dim * 2).float().to(self.device))

            batch_entity_pair_vec_list.append(torch.stack(sent_entity_pair_rep_list))

        batch_added_marker_entity_span_vec = pad_sequence(batch_entity_pair_vec_list, batch_first=True,
                                                          padding_value=padding_value)

        batch_added_marker_entity_span_vec = self.linear_transform(batch_added_marker_entity_span_vec)
        batch_added_marker_entity_span_vec = F.gelu(batch_added_marker_entity_span_vec)
        batch_added_marker_entity_span_vec = self.layer_normalization(batch_added_marker_entity_span_vec)

        return batch_added_marker_entity_span_vec, batch_entity_pair_span_list, batch_sent_len_list


class MyBinaryClassifier(nn.Module):
    def __init__(self, TAGS_fields, input_dim, device, ignore_index=None, loss_weight=None):
        super(MyBinaryClassifier, self).__init__()
        self.to(device)
        self.ignore_index = ignore_index
        self.input_dim = input_dim
        self.output_dim = len(TAGS_fields.vocab)
        self.fc1 = nn.Linear(self.input_dim, int(self.input_dim / 2), bias=False)
        self.fc2 = nn.Linear(int(self.input_dim / 2), self.output_dim, bias=False)
        self.loss_weight = loss_weight

    def forward(self, common_embedding):
        # common_embedding = nn.Dropout(p=0.5)(common_embedding)
        res = F.relu(self.fc1(common_embedding))
        res = self.fc2(res)
        return res

    def get_ce_loss(self, res, targets):
        cross_entropy_loss = torch.nn.functional.cross_entropy(res.permute(0, 2, 1), targets,
                                                               ignore_index=self.ignore_index, weight=self.loss_weight)
        return cross_entropy_loss


class MyRelationClassifier(nn.Module):
    def __init__(self, args, device):
        super(MyRelationClassifier, self).__init__()
        self.to(device)
        self.args = args
        self.device = device
        self.TAGS_my_types_classification = torchtext.legacy.data.Field(dtype=torch.long, batch_first=True,
                                                                        pad_token=None, unk_token=None)
        self.TAGS_my_types_classification.vocab = {"no": 0, "yes": 1}
        self.ignore_index = len(self.TAGS_my_types_classification.vocab)
        if self.args.Entity_Prep_Way == "entity_type_marker":
            self.relation_input_dim = self.args.Word_embedding_size
        else:
            self.relation_input_dim = 2 * self.args.Word_embedding_size
        if self.args.Weight_Loss:
            self.yes_no_weight = torch.tensor([self.args.Min_weight, self.args.Max_weight], device=self.device)
            print("self.yes_no_weight", self.yes_no_weight)
        else:
            self.yes_no_weight = None

    def get_binary_classifier(self, i):
        return getattr(self, 'my_classifier_{0}'.format(i))

    def create_classifiers(self, TAGS_Types_fields_dic,
                           TAGS_sep_entity_fields_dic,
                           TAGS_Entity_Type_fields_dic):
        self.TAGS_Types_fields_dic = TAGS_Types_fields_dic
        self.TAGS_Entity_Type_fields_dic = TAGS_Entity_Type_fields_dic
        self.TAGS_sep_entity_fields_dic = TAGS_sep_entity_fields_dic
        self.my_relation_sub_task_list = list(self.TAGS_Types_fields_dic.keys())
        self.my_entity_type_sub_task_list = list(self.TAGS_Entity_Type_fields_dic.keys())

        for sub_task in self.my_relation_sub_task_list:
            my_binary_classifier = MyBinaryClassifier(self.TAGS_my_types_classification,
                                                      self.relation_input_dim, self.device,
                                                      ignore_index=self.ignore_index)
            setattr(self, f'my_classifier_{sub_task}', my_binary_classifier)

    def forward(self, batch_added_marker_entity_span_vec):
        loss_list = []
        sub_task_res_prob_list = []
        sub_task_res_yes_no_index_list = []
        for sub_task in self.my_relation_sub_task_list:
            res = self.get_binary_classifier(sub_task)(batch_added_marker_entity_span_vec)
            loss_list.append(res)
            res = torch.max(res, 2)
            sub_task_res_prob_list.append(res[0])
            sub_task_res_yes_no_index_list.append(res[1])

        batch_pred_res_prob = torch.stack(sub_task_res_prob_list).permute(1, 2, 0)
        batch_pred_res_yes_no_index = torch.stack(sub_task_res_yes_no_index_list).permute(1, 2, 0)

        yes_flag_tensor = torch.tensor(self.TAGS_my_types_classification.vocab["yes"], device=self.device)
        no_mask_tensor = batch_pred_res_yes_no_index != yes_flag_tensor

        batch_pred_res_prob_masked = torch.masked_fill(batch_pred_res_prob, no_mask_tensor,
                                                       torch.tensor(-999, device=self.device))

        # deal the solution of all results are no, there is None classifier, commented down these two lines
        pad_tensor = torch.Tensor(batch_pred_res_prob_masked.shape[0], batch_pred_res_prob_masked.shape[1], 1).fill_(-998).to(self.device)
        batch_pred_res_prob_masked = torch.cat((batch_pred_res_prob_masked, pad_tensor), 2)

        pred_type_tensor = torch.max(batch_pred_res_prob_masked, 2)[1]

        return pred_type_tensor, loss_list

    def make_gold_for_loss(self, gold_all_sub_task_res_list, batch_entity_span_list, vocab_dic):
        batch_gold_for_loss_sub_task_list = []
        for sent_index, sent_entity_pair in enumerate(batch_entity_span_list):
            one_sent_list = []
            for entity_pair in sent_entity_pair:
                sub_task_list = []
                for sub_task, sub_task_values_list in gold_all_sub_task_res_list[sent_index].items():
                    if entity_pair in sub_task_values_list:
                        sub_task_list.append(torch.tensor(vocab_dic["yes"], dtype=torch.long, device=self.device))
                    else:
                        sub_task_list.append(torch.tensor(vocab_dic["no"], dtype=torch.long, device=self.device))
                one_sent_list.append(torch.stack(sub_task_list))

            if not one_sent_list:
                pad_sub_task_list = [torch.tensor(self.ignore_index, dtype=torch.long, device=self.device)] * len(
                    self.my_relation_sub_task_list)
                one_sent_list.append(torch.stack(pad_sub_task_list))

            batch_gold_for_loss_sub_task_list.append(torch.stack(one_sent_list))

        gold_for_loss_sub_task_tensor = pad_sequence(batch_gold_for_loss_sub_task_list, batch_first=True,
                                                     padding_value=self.ignore_index)
        gold_for_loss_sub_task_tensor = gold_for_loss_sub_task_tensor.permute(2, 0, 1)

        return gold_for_loss_sub_task_tensor

    def get_ensembled_ce_loss(self, batch_pred_for_loss_sub_task_list, batch_gold_for_loss_sub_task_tensor):
        loss_list = []
        for sub_task_index, sub_task_batch_pred in enumerate(batch_pred_for_loss_sub_task_list):
            sub_task_batch_gold = batch_gold_for_loss_sub_task_tensor[sub_task_index]
            ce_loss = F.cross_entropy(sub_task_batch_pred.permute(0, 2, 1), sub_task_batch_gold,
                                      ignore_index=self.ignore_index, weight=self.yes_no_weight, reduction='mean')
            loss_list.append(ce_loss)
        return sum(loss_list) / len(loss_list)

    def BCE_loss(self, batch_pred_for_loss_sub_task_list, batch_gold_for_loss_sub_task_tensor):
        loss_list = []
        for sub_task_index, sub_task_batch_pred in enumerate(batch_pred_for_loss_sub_task_list):
            sub_task_batch_gold = batch_gold_for_loss_sub_task_tensor[sub_task_index]
            target_tensor = torch.where(sub_task_batch_gold == self.ignore_index, torch.tensor(0, device=self.device), sub_task_batch_gold)
            target_tensor = torch.zeros(sub_task_batch_pred.shape, device=self.device).scatter_(2, target_tensor.unsqueeze(2), 1)

            criterion = nn.BCEWithLogitsLoss(pos_weight=self.yes_no_weight, reduction='mean')
            bec_loss = criterion(sub_task_batch_pred, target_tensor)
            loss_list.append(bec_loss)
        return sum(loss_list) / len(loss_list)


class MyModel(nn.Module):
    def __init__(self, encoder, classifier, args, device):
        super(MyModel, self).__init__()
        self.to(device)
        self.args = args
        self.encoder = encoder
        self.classifier = classifier

    def get_relation_data(self, batch):
        batch_entity = []
        batch_entity_type = []

        batch_entity_type_gold = self.entity_type_extraction(batch)
        TAGS_field = self.classifier.TAGS_sep_entity_fields_dic["sep_entity"][1]

        for sent_index, one_sent_entity in enumerate(batch.sep_entity):
            one_sent_temp_list = one_sent_entity[:get_sent_len(one_sent_entity, TAGS_field)]  # deal with PAD
            one_sent_temp_list = [eval(TAGS_field.vocab.itos[int(i)]) for i in one_sent_temp_list.cpu().numpy().tolist()]
            batch_entity.append(sorted(one_sent_temp_list, key=lambda s: s[0]))

            type_dic = batch_entity_type_gold[sent_index]

            batch_entity_type.append(self.provide_dic_entity_type(one_sent_temp_list, type_dic))

        assert len(batch_entity) == len(batch_entity_type)
        return batch_entity, batch_entity_type

    def provide_dic_entity_type(self, entity_list, type_dic):
        entity_type_list = []
        for entity in entity_list:
            add_flag = False
            for k, v in type_dic.items():
                if entity in v:
                    entity_type_list.append(k)
                    add_flag = True
                    break
            if not add_flag:
                entity_type_list.append("None")
        assert len(entity_type_list) == len(entity_list)
        return entity_type_list

    def forward(self, batch):
        batch_entity, batch_entity_type = self.get_relation_data(batch)
        batch_res, batch_loss = self.relation_extraction(batch, batch_entity, batch_entity_type)
        return batch_loss, batch_res

    def entity_type_extraction(self, batch):
        batch_entity_type_gold = []
        for sent_index in range(len(batch)):
            gold_one_sent_all_sub_task_res_dic = {}
            for sub_task in self.classifier.my_entity_type_sub_task_list:
                gold_one_sent_all_sub_task_res_dic.setdefault(sub_task, [])
                for entity in getattr(batch, sub_task)[sent_index]:
                    entity_span = self.classifier.TAGS_Entity_Type_fields_dic[sub_task][1].vocab.itos[entity]
                    if str(entity_span) != '[PAD]':
                        temp_pair = sorted(eval(entity_span))
                        if temp_pair not in gold_one_sent_all_sub_task_res_dic[sub_task]:
                            gold_one_sent_all_sub_task_res_dic[sub_task].append(temp_pair)
            batch_entity_type_gold.append(gold_one_sent_all_sub_task_res_dic)

        return batch_entity_type_gold

    def relation_extraction(self, batch, batch_entity, batch_entity_type):
        """ Relation extraction """

        batch_added_marker_entity_vec, batch_entity_pair_span_list, batch_sent_len_list = \
            self.encoder.batch_get_entity_pair_rep(batch.tokens, batch_entity, batch_entity_type)

        batch_pred_raw_res_list, batch_pred_for_loss_sub_task_list = self.classifier(
            batch_added_marker_entity_vec)

        batch_gold_res_list = []
        for sent_index in range(len(batch)):
            gold_one_sent_all_sub_task_res_dic = {}
            for sub_task in self.classifier.my_relation_sub_task_list:
                gold_one_sent_all_sub_task_res_dic.setdefault(sub_task, [])

                for entity_pair in getattr(batch, sub_task)[sent_index]:
                    entity_pair_span = self.classifier.TAGS_Types_fields_dic[sub_task][1].vocab.itos[
                        entity_pair]
                    if entity_pair_span != "[PAD]":
                        temp_pair = sorted(eval(entity_pair_span))
                        if temp_pair not in gold_one_sent_all_sub_task_res_dic[sub_task]:
                            gold_one_sent_all_sub_task_res_dic[sub_task].append(temp_pair)

            batch_gold_res_list.append(gold_one_sent_all_sub_task_res_dic)

        batch_pred_res_list = []
        for sent_index in range(len(batch)):
            sent_len = batch_sent_len_list[sent_index]
            pred_one_sent_all_sub_task_res_dic = {}
            for sub_task_index, sub_task in enumerate(self.classifier.my_relation_sub_task_list):
                pred_one_sent_all_sub_task_res_dic.setdefault(sub_task, [])
                for entity_pair_span, pred_type in zip(batch_entity_pair_span_list[sent_index][:sent_len],
                                                       batch_pred_raw_res_list[sent_index][:sent_len]):
                    if pred_type == sub_task_index:
                        pred_one_sent_all_sub_task_res_dic[sub_task].append(entity_pair_span)
            batch_pred_res_list.append(pred_one_sent_all_sub_task_res_dic)

        batch_gold_for_loss_sub_task_tensor = self.classifier.make_gold_for_loss(
            batch_gold_res_list, batch_entity_pair_span_list,
            self.classifier.TAGS_my_types_classification.vocab)

        if self.classifier.args.Loss == "CE":
            one_batch_relation_loss = self.classifier.get_ensembled_ce_loss(
                batch_pred_for_loss_sub_task_list, batch_gold_for_loss_sub_task_tensor)
        elif self.classifier.args.Loss == "BCE":
            one_batch_relation_loss = self.classifier.BCE_loss(batch_pred_for_loss_sub_task_list,
                                                               batch_gold_for_loss_sub_task_tensor)
        else:
            raise Exception("Choose loss error !")

        one_batch_relation_res = (batch_gold_res_list, batch_pred_res_list)

        return one_batch_relation_res, one_batch_relation_loss
