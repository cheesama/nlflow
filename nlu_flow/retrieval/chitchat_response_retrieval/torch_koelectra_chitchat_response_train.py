from Korpora import Korpora, KoreanChatbotKorpus
from tqdm import tqdm

from transformers import ElectraModel, ElectraTokenizer
from koelectra_fine_tuner import KoelectraQAFineTuner

from nlu_flow.utils import meta_db_client

from torch.nn import functional as F
from torch.utils.data import DataLoader
from torch.optim import Adam, lr_scheduler
from torch.utils.tensorboard import SummaryWriter
import torch
import torch.nn as nn

import os, sys
import multiprocessing
import argparse
import random

MAX_LEN = 64

# downlad dataset
chatbot_corpus = KoreanChatbotKorpus()

tokenizer = ElectraTokenizer.from_pretrained("monologg/koelectra-small-v2-discriminator")

questions = []
answers = []
labels = []

# prepare torch dataset
class ChatbotKorpusDataset(torch.utils.data.Dataset):
    def __init__(self, questions, answers, tokenizer):
        assert len(questions) == len(answers)

        self.tokenizer = tokenizer
        self.dataset = []

        for i, question in tqdm(enumerate(questions), desc="preparing data ..."):
            question_tokens = self.tokenizer.encode(questions[i], max_length=MAX_LEN, pad_to_max_length=True, truncation=True)
            answer_tokens = self.tokenizer.encode(answers[i], max_length=MAX_LEN, pad_to_max_length=True, truncation=True)

            self.dataset.append((question_tokens, answer_tokens, labels[i]))

    def __len__(self):
        return len(self.dataset)

    def __getitem__(self, idx):
        return torch.tensor(self.dataset[idx][0]), torch.tensor(self.dataset[idx][1]), torch.tensor(self.dataset[idx][2])

# korpora dataset add
for i, qa in enumerate(chatbot_corpus.train):
    questions.append(qa.text)
    answers.append(qa.pair)
    labels.append(i)
    
# meta db dataset add
chitchat_class_dict = dict()

meta_responses = meta_db_client.get('nlu-chitchat-responses')
for response in tqdm(meta_responses, desc='meta db chitchat questions & response organizing ...'):
    if response['class_name'] is None:
        continue

    if response['class_name']['classes'] not in chitchat_class_dict:
        chitchat_class_dict[response['class_name']['classes']] = (len(labels), [])
    chitchat_class_dict[response['class_name']['classes']][1].append(response['response'])


meta_questions = meta_db_client.get('nlu-chitchat-utterances')
for question in tqdm(meta_questions, desc='meta db chitchat dataset adding ...'):
    if question['class_name'] is None:
        continue

    for each_answer in chitchat_class_dict[question['class_name']['classes']][1]:
        questions.append(question['utterance'])
        answers.append(each_answer)
        labels.append(chitchat_class_dict[question['class_name']['classes']][0])

train_dataset = ChatbotKorpusDataset(questions, answers, tokenizer)

def train_model(n_epochs=30, lr=0.0001, batch_size=128):
    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        num_workers=multiprocessing.cpu_count(),
    )

    # model definition
    model = KoelectraQAFineTuner(max_len=MAX_LEN)

    if torch.cuda.is_available():
        model = model.cuda()

    # train model
    optimizer = Adam(model.parameters(), lr=float(lr))
    scheduler = lr_scheduler.StepLR(optimizer, 1.0, gamma=0.95)

    writer = SummaryWriter(log_dir=f"runs/epochs:{n_epochs}_lr:{lr}")
    global_step = 0

    for epoch in range(1, int(n_epochs) + 1):
        model.train()

        progress = tqdm(enumerate(train_loader), leave=False)
        for batch_idx, (question, answer, label) in progress:
            if torch.cuda.is_available():
                question = question.cuda()
                answer = answer.cuda()
                label = label.cuda()

            optimizer.zero_grad()
            loss, pos_loss, neg_loss = model(question, answer, label)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 0.5)
            optimizer.step()

            progress.set_description(
                    f"training model, epoch:{epoch}, iter: {global_step}, loss:{loss.cpu().item()}, pos_loss:{pos_loss.cpu().item()}, neg_loss:{neg_loss.cpu().item()}\n"
            )
            writer.add_scalar("train/loss", loss.cpu().item(), global_step)
            writer.add_scalar("train/pos_loss", pos_loss.cpu().item(), global_step)
            writer.add_scalar("train/neg_loss", neg_loss.cpu().item(), global_step)
            global_step += 1

        torch.save(model.state_dict(), "transformer_chitchat_retrieval_model.modeldict")
        scheduler.step()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n_epochs", default=20)
    parser.add_argument("--lr", default=0.0001)
    args = parser.parse_args()

    train_model(int(args.n_epochs), float(args.lr))
