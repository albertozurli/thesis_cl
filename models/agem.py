import statistics
import torch

from utils.buffer import Buffer
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter
from tqdm import tqdm

from models.gem import store_gradient, overwrite_gradient
from utils.metrics import backward_transfer, forgetting, forward_transfer
from utils.evaluation import evaluate_past, test_epoch, evaluate_next
from utils.utils import binary_accuracy

import pandas as pd
import numpy as np


def train_agem(model, loss, device, optimizer, train_set, test_set, suffix, config):
    train_writer = SummaryWriter('./runs/a_gem/train/' + suffix)
    a_gem = AGEM(config, device, model, loss, optimizer)
    accuracy = []

    # N SummaryWriter for N domains
    if config['evaluate']:
        text_file = open("a_gem_" + suffix + ".txt", "a")
        text_file.write("A-GEM LEARNING \n")
        test_writer = SummaryWriter('./runs/a_gem/test/' + suffix)
        writer_list = []
        test_list = [[] for _ in range(len(train_set))]
        for i in range(len(train_set)):
            writer_list.append(SummaryWriter(f'./runs/a_gem/test/{suffix}/d_{i}'))

    # Eval without training
    _, _, random_mean_accuracy, _ = evaluate_past(a_gem.model, len(test_set) - 1, test_set, a_gem.loss, device)

    # Train
    for index, data_set in enumerate(train_set):
        a_gem.model.train()
        print(f"----- DOMAIN {index} -----")
        train_loader = DataLoader(data_set, batch_size=config["batch_size"], shuffle=False)

        for epoch in tqdm(range(config['epochs'])):
            a_gem.model.train()

            epoch_loss = []
            epoch_acc = []
            for j, (x, y) in enumerate(train_loader):

                # Gradient current task
                a_gem.optimizer.zero_grad()
                x = x.to(device)
                output = a_gem.model(x)
                y = y.to(device)
                s_loss = a_gem.loss(output, y.squeeze(1))

                if config['cnn']:
                    l1_reg = 0
                    for param in a_gem.model.parameters():
                        l1_reg += torch.norm(param, 1)
                    s_loss += config['l1_lambda'] * l1_reg

                _, pred = torch.max(output.data, 1)
                acc = binary_accuracy(pred, y.squeeze(1))
                epoch_loss.append(s_loss.item())
                epoch_acc.append(acc.item())

                s_loss.backward()

                if not a_gem.buffer.is_empty():
                    store_gradient(a_gem.model.parameters(), a_gem.grad_xy, a_gem.grad_dims)

                    buf_inputs, buf_labels, _ = a_gem.buffer.get_data(config['batch_size'])
                    a_gem.optimizer.zero_grad()
                    buf_outputs = a_gem.model(torch.stack(buf_inputs))
                    penalty = a_gem.loss(buf_outputs, torch.stack(buf_labels).squeeze(1))
                    penalty.backward()
                    store_gradient(a_gem.model.parameters(), a_gem.grad_er, a_gem.grad_dims)

                    dot_prod = torch.dot(a_gem.grad_xy, a_gem.grad_er)
                    if dot_prod.item() < 0:
                        gradient_tilde = project(gxy=a_gem.grad_xy, ger=a_gem.grad_er)
                        overwrite_gradient(a_gem.model.parameters(), gradient_tilde, a_gem.grad_dims)
                    else:
                        overwrite_gradient(a_gem.model.parameters(), a_gem.grad_xy, a_gem.grad_dims)

                a_gem.optimizer.step()

            train_writer.add_scalar('Train/loss', statistics.mean(epoch_loss),
                                    epoch + (config['epochs'] * index))
            train_writer.add_scalar('Train/accuracy', statistics.mean(epoch_acc),
                                    epoch + (config['epochs'] * index))

            if (epoch % 100 == 0) or (epoch == (config['epochs'] - 1)):
                print(f'\nEpoch {epoch:03}/{config["epochs"]} | Loss: {statistics.mean(epoch_loss):.5f} '
                      f'| Acc: {statistics.mean(epoch_acc):.2f}%')

            # Test each epoch
            if config['evaluate']:
                tmp_list = []
                # Past tasks
                for past in range(index):
                    test_loader = DataLoader(test_set[past], batch_size=1, shuffle=False)
                    tmp, _ = test_epoch(a_gem.model, test_loader, a_gem.loss, device)
                    writer_list[past].add_scalar('Test/domain_accuracy', statistics.mean(tmp),
                                                 epoch + (config['epochs'] * index))
                    test_list[past].append(statistics.mean(tmp))
                    for t in tmp:
                        tmp_list.append(t)
                # Current task
                test_loader = DataLoader(test_set[index], batch_size=1, shuffle=False)
                tmp, loss_task = test_epoch(a_gem.model, test_loader, a_gem.loss, device)
                writer_list[index].add_scalar('Test/domain_accuracy', statistics.mean(tmp),
                                              epoch + (config['epochs'] * index))
                writer_list[index].add_scalar('Test/domain_loss', statistics.mean(loss_task),
                                              epoch + (config['epochs'] * index))
                test_list[index].append(statistics.mean(tmp))
                for t in tmp:
                    tmp_list.append(t)

                avg = sum(tmp_list) / len(tmp_list)
                test_writer.add_scalar('Test/mean_accuracy', avg, epoch + (config['epochs'] * index))

        a_gem.end_task(train_set, index)

        # Test at the end of domain
        evaluation, error, mean_evaluation, mean_error = evaluate_past(a_gem.model, index, test_set, a_gem.loss, device)
        print(f"Mean Error: {statistics.mean(error):.5f} | Mean Acc: {statistics.mean(evaluation):.2f}%")
        accuracy.append(mean_evaluation)
        if config['evaluate']:
            text_file.write(f"---Evaluation after domain {index}--- \n")
            for i, a in enumerate(mean_evaluation):
                text_file.write(f"Domain {i} | Error: {mean_error[i]:.5f} | Acc: {a:.2f}%\n")
            text_file.write(f"Mean Error: {statistics.mean(error):.5f} | "
                            f"Mean Acc: {statistics.mean(evaluation):.2f}% \n")

        if index != len(train_set) - 1:
            accuracy[index].append(evaluate_next(a_gem.model, index, test_set, a_gem.loss, device))

        torch.save(a_gem.model.state_dict(), f'checkpoints/a_gem/model_d{index}.pt')

    # Compute transfer metrics
    backward = backward_transfer(accuracy)
    forward = forward_transfer(accuracy, random_mean_accuracy)
    forget = forgetting(accuracy)
    print(f'Backward transfer: {backward}')
    print(f'Forward transfer: {forward}')
    print(f'Forgetting: {forget}')

    if config['evaluate']:
        text_file.write(f"Backward: {backward}\n")
        text_file.write(f"Forward: {forward}\n")
        text_file.write(f"Forgetting: {forget}\n")
        text_file.close()

        df = pd.DataFrame(test_list)
        df.to_csv(f"a_gem_{suffix}.csv")


def project(gxy, ger):
    cor = torch.dot(gxy, ger) / torch.dot(ger, ger)
    return gxy - cor * ger


class AGEM:
    def __init__(self, config, device, model, loss, optimizer):
        self.config = config
        self.device = device
        self.model = model
        self.loss = loss
        self.optimizer = optimizer

        self.buffer = Buffer(self.config['buffer_size'], self.device)
        self.grad_dims = []
        for p in self.model.parameters():
            self.grad_dims.append(p.data.numel())
        self.grad_xy = torch.Tensor(np.sum(self.grad_dims)).to(self.device)
        self.grad_er = torch.Tensor(np.sum(self.grad_dims)).to(self.device)

    def end_task(self, dataset, index):
        # Add data to the buffer
        num_samples = self.config['buffer_size'] // len(dataset)

        loader = DataLoader(dataset[index], batch_size=num_samples, shuffle=False)
        x, y = next(iter(loader))
        self.buffer.add_data(examples=x.to(self.device), labels=y.to(self.device))
