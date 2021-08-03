import statistics
import numpy as np
import pandas as pd
import torch
import matplotlib.pyplot as plt
import talib

from pathlib import Path


def compute_diff(data):
    diff = np.diff(np.array(data), axis=0)
    return diff.tolist()


def indicators(data):
    """
    :param data: data
    :return: np array of each indicator
    """
    cmo = talib.CMO(np.array(data), timeperiod=10).reshape(-1, 1)
    roc = talib.ROC(np.array(data), timeperiod=5).reshape(-1, 1)
    rsi = talib.RSI(np.array(data), timeperiod=5).reshape(-1, 1)
    wma = talib.WMA(np.array(data), timeperiod=20).reshape(-1, 1)
    ppo = talib.PPO(np.array(data), fastperiod=5, slowperiod=10, matype=0).reshape(-1, 1)
    return cmo, roc, rsi, wma, ppo


def timeperiod(filename):
    month = "monthly"
    day = "daily"
    if month in filename:
        return 4
    elif day in filename:
        return 30
    else:
        return 0


def split_with_indicators(data, chps, n_step):
    """
    :param data: data
    :param chps: list of changepoint detected
    :param n_step: size of a sequence
    :return: train set and test set divided
    """
    train_data = []
    test_data = []

    cmo, roc, rsi, wma, ppo = indicators(data)
    data = np.array(data).reshape(-1, 1)
    data_split = np.split(data, chps)
    cmo_split = np.split(cmo, chps)
    roc_split = np.split(roc, chps)
    rsi_split = np.split(rsi, chps)
    wma_split = np.split(wma, chps)
    ppo_split = np.split(ppo, chps)
    for index, (subdata, subcmo, subroc, subrsi, subwma, subppo) in \
            enumerate(zip(data_split, cmo_split, roc_split, rsi_split, wma_split, ppo_split)):
        seq = []
        i = 0
        while i < len(subdata):
            end_seq = i + n_step
            if end_seq > (len(subdata) - n_step):
                break
            seq_x, y = subdata[i:end_seq], subdata[end_seq + n_step - 1]
            seq_cmo = subcmo[i:end_seq]
            seq_roc = subroc[i:end_seq]
            seq_rsi = subrsi[i:end_seq]
            seq_wma = subwma[i:end_seq]
            seq_ppo = subppo[i:end_seq]
            domain = index
            input = np.concatenate((seq_x, seq_cmo, seq_roc, seq_rsi, seq_wma, seq_ppo), axis=0)
            # input = input.squeeze()
            input = np.append(input, domain)

            label = 0.  # Target value lower or equal than input sequence
            if y > statistics.mean(seq_x.flatten()):
                label = 1.  # Target value greater than input sequence

            input = torch.Tensor(input)
            label = torch.Tensor(np.array(label))
            if not torch.isnan(torch.sum(input)):
                seq.append((input, label))
            i += 1

        train_data.append(seq[:round(len(seq) * 0.75)])
        test_data.append(seq[round(len(seq) * 0.75):])

    return train_data, test_data


def split_data(data, chps, n_step):
    """
    :param data: data
    :param chps: list of changepoint detected
    :param n_step: size of a sequence
    :return: train set and test set divided
    """
    train_data = []
    test_data = []
    tmp = np.split(data, chps)
    for index, subdata in enumerate(tmp):
        seq = []
        i = 0
        while i < len(subdata):
            end_seq = i + n_step
            if end_seq > (len(subdata) - n_step):
                break
            seq_x, y = subdata[i:end_seq], subdata[end_seq + n_step - 1]
            domain = index
            input = np.append(seq_x, domain)

            label = 0.  # Target value lower or equal than input sequence
            if y > statistics.mean(seq_x.flatten()):
                label = 1.  # Target value greater than input sequence

            input = torch.Tensor(input)
            label = torch.Tensor(np.array(label))
            seq.append((input, label))
            i += 1
        train_data.append(seq[:round(len(seq) * 0.75)])
        test_data.append(seq[round(len(seq) * 0.75):])

    return train_data, test_data


def read_csv(filename):
    """
    :param filename: name of the file
    :return: list of values extracted from the file
    """
    path = Path.cwd()
    csv_path = path.joinpath('dataset', filename)
    df = pd.read_csv(csv_path)
    value_list = df.iloc[:, 1].to_list()
    return value_list


def check_changepoints(filename):
    path = Path.cwd()
    file_path = path.joinpath('chp_list.txt')
    rows = [x.strip() for x in open(file_path, 'r').readlines()]
    chps = np.zeros(1)
    for r in rows:
        tmp = r.split(',')
        if tmp[0] == filename:
            value_list = tmp[1:]
            chps = np.array(value_list, dtype=np.int)
            return True, chps
    return False, chps


def binary_accuracy(y_pred, y_true):
    """
    :param y_pred: label predicted
    :param y_true: true label
    :return: accuracy
    """
    y_pred_tag = torch.round(y_pred)
    result_sum = (y_pred_tag == y_true).sum().float()
    acc = result_sum / y_true.shape[0]
    acc = torch.round(acc * 100)
    return acc


def eval_bayesian(chps, raw_data):
    """
    Visual evaluation of Bayesian changepoint detection and split in different domains
    :param chps: array of changepoint
    :param raw_data:
    """
    plt.figure(figsize=(10, 6))
    plt.plot(raw_data)
    plt.xlabel("Timestep")
    plt.ylabel("Price")
    plt.grid(True)
    for i in chps:
        plt.axvline(i, color="red")
    plt.title("Bayesian Online")
    plt.xlabel("Timestep")
    plt.ylabel("Price")
    plt.show()


    # Evaluation of train/test split
    splits = np.split(raw_data, chps)
    for index, subdata in enumerate(splits):
        plt.plot(subdata[:round(len(subdata) * 0.75)], color='red', label='Train')
        tmp = np.arange(round(len(subdata) * 0.75), len(subdata))
        plt.plot(tmp, subdata[round(len(subdata) * 0.75):], color='green', label='Test')
        plt.legend(loc='best')
        plt.title(f'Test/Train split domain {index}')
        plt.show()
