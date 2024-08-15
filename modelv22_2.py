# !/usr/bin/env python3
"""
==== No Bugs in code, just some Random Unexpected FEATURES ====
┌─────────────────────────────────────────────────────────────┐
│┌───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┐│
││Esc│!1 │@2 │#3 │$4 │%5 │^6 │&7 │*8 │(9 │)0 │_- │+= │|\ │`~ ││
│├───┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴───┤│
││ Tab │ Q │ W │ E │ R │ T │ Y │ U │ I │ O │ P │{[ │}] │ BS  ││
│├─────┴┬──┴┬──┴┬──┴┬──┴┬──┴┬──┴┬──┴┬──┴┬──┴┬──┴┬──┴┬──┴─────┤│
││ Ctrl │ A │ S │ D │ F │ G │ H │ J │ K │ L │: ;│" '│ Enter  ││
│├──────┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴─┬─┴────┬───┤│
││ Shift  │ Z │ X │ C │ V │ B │ N │ M │< ,│> .│? /│Shift │Fn ││
│└─────┬──┴┬──┴──┬┴───┴───┴───┴───┴───┴──┬┴───┴┬──┴┬─────┴───┘│
│      │Fn │ Alt │         Space         │ Alt │Win│   HHKB   │
│      └───┴─────┴───────────────────────┴─────┴───┘          │
└─────────────────────────────────────────────────────────────┘

UIE torch版本实现，包含模型预处理/后处理函数。

Author: pankeyu
Date: 2022/10/18
"""
import json
from typing import List

import torch
import torch.nn as nn
import numpy as np
from transformers import AutoModel, AutoTokenizer
from transformers import BertModel
from transformers import BertTokenizer
import os

import matplotlib.pyplot as plt
from PIL import Image
import datetime
from matplotlib.colors import LinearSegmentedColormap, PowerNorm
import time
# 把设计的部分打包成了一个block，使用了3次
# 其中设计的部分包含 2 3 4 5
# 加入了通道注意力，来解决局部信息中存在冗余的问题
# 设置了预训练bert可以冻结的函数
# 设置了头指针和尾指针来自不同的embedding
# block中的卷积层被替换成平均池化了
# 基于v20做了头尾指针的交叉注意力，并通过detach来解决反向传播时互相影响的问题。
# 将myblock全部替换为CrossAttentionEncoderLayer了，用于单独测试v21的头尾指针交叉注意力的效果
class CrossAttentionEncoderLayer(nn.Module):
    def __init__(self, d_model, nhead, dim_feedforward=2048, dropout=0.1):
        super(CrossAttentionEncoderLayer, self).__init__()

        # 交叉注意力
        self.cross_attention = nn.MultiheadAttention(d_model, nhead)

        # 前馈神经网络
        self.feedforward = nn.Sequential(
            nn.Linear(d_model, dim_feedforward),
            nn.ReLU(),
            nn.Linear(dim_feedforward, d_model),
        )

        # 层标准化
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)

        # 丢弃层
        self.dropout = nn.Dropout(dropout)

    def forward(self, src, memory, src_mask=None, memory_mask=None):
        # 交叉注意力
        cross_attention_output, cross_attention_output_weight = self.cross_attention(src, memory, memory, attn_mask=memory_mask)
        # now = datetime.datetime.now()

        # # 格式化日期时间字符串，例如：20230618-153045
        # formatted_date = now.strftime("%Y%m%d-%H%M%S")
        # # print('0000000000000000000000000000000000000000000000000')
        # for i in cross_attention_output_weight:
        #     time.sleep(1)
        #     i = i.sum(dim=0).cpu().detach().numpy()
        #     # i = (i - i.min()) / (i.max() - i.min())
        #     norm = PowerNorm(gamma=0.4)
        #     i = i[0:60, 0:60]
        #     # colors = [(1, 1, 1), (0, 0, 0)]  # 白色到黑色
        #     colors = [(1, 1, 1), (0, 1, 1)]
        #     cmap_name = 'my_list'
        #     cm = LinearSegmentedColormap.from_list(cmap_name, colors, N=5)
        #     plt.imshow(i, cmap=cm, norm=norm)
        #     plt.colorbar()  # 显示颜色条
        #     plt.savefig('logs/heatmap'+formatted_date+'.png')
        #     print('logs/heatmap'+formatted_date+'.png')
        #     plt.close()
        #     # print('1111111111111111111111111111111111111111111111111111')

        # Add & Norm
        src = src + self.dropout(cross_attention_output)
        src = self.norm1(src)

        # 前馈神经网络
        feedforward_output = self.feedforward(src)

        # Add & Norm
        src = src + self.dropout(feedforward_output)
        src = self.norm2(src)

        return src
        
        
class UIE(nn.Module):
    def initialize_model(self):
        model_name = "pretrain/chinese-roberta-wwm-ext"
        self.encoder = AutoModel.from_pretrained(model_name)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
    
    def freeze(self, flag):
        if flag == True:
            for param in self.encoder.embeddings.parameters():
                param.requires_grad = False
            for layer in self.encoder.encoder.layer.parameters():
                layer.requires_grad = False
            self.freeze_f = True
        if flag == False:
            for param in self.encoder.embeddings.parameters():
                param.requires_grad = True
            for layer in self.encoder.encoder.layer.parameters():
                layer.requires_grad = True
            self.freeze_f = False

    def __init__(self, cuda, batchsize):
        super().__init__()
        self.device = cuda
        self.initialize_model()
        self.freeze(flag=True)
        self.bert_config = self.encoder.config
        hidden_size = self.bert_config.hidden_size
        self.my_block1 = CrossAttentionEncoderLayer(d_model=hidden_size, nhead=8)
        self.my_block2 = CrossAttentionEncoderLayer(d_model=hidden_size, nhead=8)
        # self.cross = CrossAttentionEncoderLayer(d_model=hidden_size, nhead=8)
        # self.cross2 = CrossAttentionEncoderLayer(d_model=hidden_size, nhead=8)
        self.linear_start = nn.Linear(hidden_size, 1)
        self.linear_end = nn.Linear(hidden_size, 1)
        self.sigmoid = nn.Sigmoid()
        # for param in self.encoder.embeddings.parameters():
        #     param.requires_grad = False
        # for layer in self.encoder.encoder.layer.parameters():
        #     layer.requires_grad = False
        self.freeze_f = True
        # 前馈神经网络
        dim_feedforward = 2048
        self.feedforward = nn.Sequential(
            nn.Linear(hidden_size, dim_feedforward),
            nn.ReLU(),
            nn.Linear(dim_feedforward, hidden_size),
        )

        self.feedforward2 = nn.Sequential(
            nn.Linear(hidden_size, dim_feedforward),
            nn.ReLU(),
            nn.Linear(dim_feedforward, hidden_size),
        )

        # 层标准化
        self.norm1 = nn.LayerNorm(hidden_size)
        self.norm2 = nn.LayerNorm(hidden_size)

        # 丢弃层
        self.dropout = nn.Dropout(0.2)
        

    def forward(
        self,
        input_ids: torch.tensor,
        token_type_ids: torch.tensor,
        attention_mask=None,
        pos_ids=None,
        epoch_num = None,
    ) -> tuple:
        """
        forward 函数，返回开始/结束概率向量。

        Args:
            input_ids (torch.tensor): (batch, seq_len)
            token_type_ids (torch.tensor): (batch, seq_len)
            attention_mask (torch.tensor): (batch, seq_len)
            pos_ids (torch.tensor): (batch, seq_len)

        Returns:
            tuple:  start_prob -> (batch, seq_len)
                    end_prob -> (batch, seq_len)
        """

        # if epoch_num == 2:
        #     self.freeze(flag=False)
        # print(self.freeze_f)
        sequence_output = self.encoder(
            input_ids=input_ids,
            token_type_ids=token_type_ids,
            position_ids=pos_ids,
            attention_mask=attention_mask,
        )["last_hidden_state"]
        # print(self.encoder)
        # print('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
        
        # print(self.freeze_f)
        # se_output = self.encoder(
        #     input_ids=input_ids,
        #     token_type_ids=token_type_ids,
        #     position_ids=pos_ids,
        #     attention_mask=attention_mask,
        #     output_attentions=True
        # )["attentions"][-1]
        
        # sequence_output = sequence_output.squeeze(0)
        # print('sequence', sequence_output.shape)
        
        
        # print(self.freeze_f)
        # now = datetime.datetime.now()
        # time.sleep(1)

        # # 格式化日期时间字符串，例如：20230618-153045
        # formatted_date = now.strftime("%Y%m%d-%H%M%S")
        # i = se_output.squeeze().sum(dim=0).cpu().detach().numpy()
        # # i = (i - i.min()) / (i.max() - i.min())
        # i = i[0:60, 0:60]
        # norm = PowerNorm(gamma=0.4)
        # colors = [(1, 1, 1), (0, 1, 1)]  # 白色到黑色
        # cmap_name = 'my_list'
        # cm = LinearSegmentedColormap.from_list(cmap_name, colors, N=5)
        # plt.imshow(i, cmap=cm, norm = norm)
        # plt.colorbar()  # 显示颜色条
        # plt.savefig('logs/se_output'+formatted_date+'.png')
        # plt.close()
        
        
        # print('start_idx_0')
        ge_output = self.my_block1(sequence_output.permute(1, 0, 2),sequence_output.permute(1, 0, 2)).permute(1, 0, 2)
        # print('start_idx_1')
        # print('end_idx_0')
        ge_output2 = self.my_block2(sequence_output.permute(1, 0, 2),sequence_output.permute(1, 0, 2)).permute(1, 0, 2)
        # print('end_idx_1')
        # cp_output = ge_output.detach()
        # cp_output2 = ge_output2.detach()

        # output = self.cross(ge_output.permute(1, 0, 2), cp_output2.permute(1, 0, 2)).permute(1, 0, 2)
        # output2 = self.cross2(ge_output2.permute(1, 0, 2), cp_output.permute(1, 0, 2)).permute(1, 0, 2)
        
        start_logits = self.linear_start(ge_output)       # (batch, seq_len, 1)
        start_logits = torch.squeeze(start_logits, -1)          # (batch, seq_len)
        start_prob = self.sigmoid(start_logits)                 # (batch, seq_len)
        end_logits = self.linear_end(ge_output2)           # (batch, seq_len, 1)
        end_logits = torch.squeeze(end_logits, -1)              # (batch, seq_len)
        end_prob = self.sigmoid(end_logits)                     # (batch, seq_len)
        return start_prob, end_prob


def get_bool_ids_greater_than(probs: list, limit=0.5, return_prob=False) -> list:
    """
    筛选出大于概率阈值的token_ids。

    Args:
        probs (_type_): 
        limit (float, optional): _description_. Defaults to 0.5.
        return_prob (bool, optional): _description_. Defaults to False.

    Returns:
        list: [1, 3, 5, ...] (return_prob=False) 
                or 
            [(1, 0.56), (3, 0.78), ...] (return_prob=True)

    Reference:
        https://github.com/PaddlePaddle/PaddleNLP/blob/a12481fc3039fb45ea2dfac3ea43365a07fc4921/paddlenlp/taskflow/utils.py#L810
    """
    probs = np.array(probs)
    dim_len = len(probs.shape)
    if dim_len > 1:
        result = []
        for p in probs:
            result.append(get_bool_ids_greater_than(p, limit, return_prob))
        return result
    else:
        result = []
        for i, p in enumerate(probs):
            if p > limit:
                if return_prob:
                    result.append((i, p))
                else:
                    result.append(i)
        return result


def get_span(start_ids: list, end_ids: list, with_prob=False) -> set:
    """
    输入start_ids和end_ids，计算answer span列表。

    Args:
        start_ids (list): [1, 2, 10]
        end_ids (list):  [4, 12]
        with_prob (bool, optional): _description_. Defaults to False.

    Returns:
        set: set((2, 4), (10, 12))

    Reference:
        https://github.com/PaddlePaddle/PaddleNLP/blob/a12481fc3039fb45ea2dfac3ea43365a07fc4921/paddlenlp/taskflow/utils.py#L835
    """
    if with_prob:
        start_ids = sorted(start_ids, key=lambda x: x[0])
        end_ids = sorted(end_ids, key=lambda x: x[0])
    else:
        start_ids = sorted(start_ids)
        end_ids = sorted(end_ids)

    start_pointer = 0
    end_pointer = 0
    len_start = len(start_ids)
    len_end = len(end_ids)
    couple_dict = {}
    while start_pointer < len_start and end_pointer < len_end:
        if with_prob:
            if start_ids[start_pointer][0] == end_ids[end_pointer][0]:
                couple_dict[end_ids[end_pointer]] = start_ids[start_pointer]
                start_pointer += 1
                end_pointer += 1
                continue
            if start_ids[start_pointer][0] < end_ids[end_pointer][0]:
                couple_dict[end_ids[end_pointer]] = start_ids[start_pointer]
                start_pointer += 1
                continue
            if start_ids[start_pointer][0] > end_ids[end_pointer][0]:
                end_pointer += 1
                continue
        else:
            if start_ids[start_pointer] == end_ids[end_pointer]:
                couple_dict[end_ids[end_pointer]] = start_ids[start_pointer]
                start_pointer += 1
                end_pointer += 1
                continue
            if start_ids[start_pointer] < end_ids[end_pointer]:
                couple_dict[end_ids[end_pointer]] = start_ids[start_pointer]
                start_pointer += 1
                continue
            if start_ids[start_pointer] > end_ids[end_pointer]:
                end_pointer += 1
                continue
    result = [(couple_dict[end], end) for end in couple_dict]
    result = set(result)
    return result


def convert_inputs(tokenizer, prompts: List[str], contents: List[str], max_length=512) -> dict:
    """
    处理输入样本，包括prompt/content的拼接和offset的计算。

    Args:
        tokenizer (tokenizer): tokenizer
        prompt (List[str]): prompt文本列表
        content (List[str]): content文本列表
        max_length (int): 句子最大长度

    Returns:
        dict -> {
                    'input_ids': tensor([[1, 57, 405, ...]]), 
                    'token_type_ids': tensor([[0, 0, 0, ...]]), 
                    'attention_mask': tensor([[1, 1, 1, ...]]), 
                    'pos_ids': tensor([[0, 1, 2, 3, 4, 5,...]])
                    'offset_mapping': tensor([[[0, 0], [0, 1], [1, 2], [0, 0], [3, 4], ...]])
            }
        
    Reference:
        https://github.com/PaddlePaddle/PaddleNLP/blob/a12481fc3039fb45ea2dfac3ea43365a07fc4921/model_zoo/uie/utils.py#L150
    """
    inputs = tokenizer(text=prompts,                 # [SEP]前内容
                        text_pair=contents,          # [SEP]后内容
                        truncation=True,             # 是否截断
                        max_length=max_length,       # 句子最大长度
                        padding="max_length",        # padding类型
                        return_offsets_mapping=True, # 返回offsets用于计算token_id到原文的映射
                )
    pos_ids = []
    for i in range(len(contents)):
        pos_ids += [[j for j in range(len(inputs['input_ids'][i]))]]
    pos_ids = torch.tensor(pos_ids)
    inputs['pos_ids']=pos_ids

    offset_mappings = [[list(x) for x in offset] for offset in inputs["offset_mapping"]]
    
    # * Desc:
    # *    经过text & text_pair后，生成的offset_mapping会将prompt和content的offset独立计算，
    # *    这里将content的offset位置补回去。
    # *
    # * Example:
    # *    offset_mapping(before):[[0, 0], [0, 1], [1, 2], [0, 0], [0, 1], [1, 2], [2, 3], ...]
    # *    offset_mapping(after):[[0, 0], [0, 1], [1, 2], [0, 0], [2, 3], [4, 5], [5, 6], ...]
    # *
    for i in range(len(offset_mappings)):                           # offset 重计算
        bias = 0
        for index in range(1, len(offset_mappings[i])):
            mapping = offset_mappings[i][index]
            if mapping[0] == 0 and mapping[1] == 0 and bias == 0:
                bias = offset_mappings[i][index - 1][1]
            if mapping[0] == 0 and mapping[1] == 0:
                continue
            offset_mappings[i][index][0] += bias
            offset_mappings[i][index][1] += bias
    
    inputs['offset_mapping'] = offset_mappings

    for k, v in inputs.items():                                     # list转tensor
        inputs[k] = torch.LongTensor(v)

    return inputs


def map_offset(ori_offset, offset_mapping):
    """
    map ori offset to token offset
    """
    for index, span in enumerate(offset_mapping):
        if span[0] <= ori_offset < span[1]:
            return index
    return -1


def convert_example(examples, tokenizer, max_seq_len):
    """
    将样本数据转换为模型接收的输入数据。

    Args:
        examples (dict): 训练数据样本, e.g. -> {
                                                "text": [
                                                            {
                                                                "content": "北京是中国的首都", 
                                                                "prompt": "城市",
                                                                "result_list": [{"text": "北京", "start": 0, "end": 2}]
                                                            },
                                                        ...
                                                ]
                                            }

    Returns:
        dict (str: np.array) -> tokenized_output = {
                            'input_ids': [[101, 3928, ...], [101, 4395, ...]], 
                            'token_type_ids': [[0, 0, ...], [0, 0, ...]],
                            'attention_mask': [[1, 1, ...], [1, 1, ...]],
                            'pos_ids': [[0, 1, 2, ...], [0, 1, 2, ...], ...],
                            'start_ids': [[0, 1, 0, ...], [0, 0, ..., 1, ...]],
                            'end_ids': [[0, 0, 1, ...], [0, 0, ...]]
                        }
    """
    tokenized_output = {
            'input_ids': [], 
            'token_type_ids': [],
            'attention_mask': [],
            'pos_ids': [],
            'start_ids': [],
            'end_ids': []
        }

    for example in examples['text']:
        example = json.loads(example)
        try:
            encoded_inputs = tokenizer(
                text=example['prompt'],
                text_pair=example['content'],
                stride=len(example['prompt']),
                truncation=True,
                max_length=max_seq_len,
                padding='max_length',
                return_offsets_mapping=True)
        except:
            print('[Warning] ERROR Sample: ', example)
            exit()
        offset_mapping = [list(x) for x in encoded_inputs["offset_mapping"]]

        """
        经过text & text_pair后，生成的offset_mapping会将prompt和content的offset独立计算，
        这里将content的offset位置补回去。

        offset_mapping(before):[[0, 0], [0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 7], [0, 0], [0, 1], [1, 2], [2, 3], [3, 4], ...]
        offset_mapping(after):[[0, 0], [0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 7], [0, 0], [8, 9], [9, 10], [10, 11], [11, 12], ...]
        """
        bias = 0
        for index in range(len(offset_mapping)):
            if index == 0:
                continue
            mapping = offset_mapping[index]
            if mapping[0] == 0 and mapping[1] == 0 and bias == 0:
                bias = index
            if mapping[0] == 0 and mapping[1] == 0:
                continue
            offset_mapping[index][0] += bias
            offset_mapping[index][1] += bias

        start_ids = [0 for x in range(max_seq_len)]
        end_ids = [0 for x in range(max_seq_len)]

        for item in example["result_list"]:
            start = map_offset(item["start"] + bias, offset_mapping)    # 计算真实的start token的id
            end = map_offset(item["end"] - 1 + bias, offset_mapping)    # 计算真实的end token的id
            start_ids[start] = 1.0                                      # one-hot vector
            end_ids[end] = 1.0                                          # one-hot vector

        pos_ids = [i for i in range(len(encoded_inputs['input_ids']))]
        tokenized_output['input_ids'].append(encoded_inputs["input_ids"])
        tokenized_output['token_type_ids'].append(encoded_inputs["token_type_ids"])
        tokenized_output['attention_mask'].append(encoded_inputs["attention_mask"])
        tokenized_output['pos_ids'].append(pos_ids)
        tokenized_output['start_ids'].append(start_ids)
        tokenized_output['end_ids'].append(end_ids)

    for k, v in tokenized_output.items():
        tokenized_output[k] = np.array(v, dtype='int64')

    return tokenized_output


if __name__ == "__main__":
    model = UIE()
    tokenizer = BertTokenizer.from_pretrained("pretrain/chinese-roberta-wwm-ext")
    max_seq_len = 50
    text = "大家好我是渣渣辉！"
    tokens = tokenizer(
            text,
            max_length=max_seq_len,
            padding='max_length',
            truncation=True,
            return_tensors='pt'
        )
    input_ids = tokens['input_ids']
    attention_mask = tokens['attention_mask']
    token_type_ids = tokens['token_type_ids']
    start_prob, end_prob = model(input_ids=input_ids, attention_mask=attention_mask, token_type_ids=token_type_ids)
    print(start_prob.shape, end_prob.shape)