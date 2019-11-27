'''Author: HC Ruiz Euler; 
DNPU based network of devices to solve complex tasks 25/10/2019

'''


import torch
import numpy as np
import torch.nn as nn
from bspyproc.utils.pytorch import TorchUtils
from bspyproc.processors.simulation.dopanet import DNPU


class DNPU_NET(nn.Module):
    def __init__(self, in_dict,
                 path=r'../Data/Models/checkpoint3000_02-07-23h47m.pt'):
        super().__init__()
        self.in_dict = in_dict
        self.conversion_offset = torch.tensor(-0.6)
        offset_min = -0.35
        offset_max = 0.7
        offset = offset_min + offset_max*np.random.rand(1, 2)
        offset = TorchUtils.get_tensor_from_numpy(offset)
        self.offset = nn.Parameter(offset)
        self.offset_min = offset_min
        self.offset_max = offset_max

        self.input_node1 = DNPU(in_dict['input_node1'], path=path)
        self.input_node2 = DNPU(in_dict['input_node2'], path=path)
        self.bn1 = nn.BatchNorm1d(2, affine=False)

        self.hidden_node1 = DNPU(in_dict['hidden_node1'], path=path)
        self.hidden_node2 = DNPU(in_dict['hidden_node2'], path=path)
        self.bn2 = nn.BatchNorm1d(2, affine=False)

        self.output_node = DNPU(in_dict['output_node'], path=path)

    def forward(self, x):
        # Pass through input layer
        x = x + self.offset
        x1 = self.input_node1(x)
        x2 = self.input_node2(x)
        # --- BatchNorm --- #
        h = self.bn1(torch.cat((x1, x2), dim=1))
        std1 = np.sqrt(torch.mean(self.bn1.running_var).cpu().numpy())
        cut = 2*std1
        # Pass through first hidden layer
        h = torch.tensor(1.8/(4*std1)) * \
            torch.clamp(h, min=-cut, max=cut) + self.conversion_offset
        h1 = self.hidden_node1(h)
        h2 = self.hidden_node2(h)
        # --- BatchNorm --- #
        h = self.bn2(torch.cat((h1, h2), dim=1))
        std2 = np.sqrt(torch.mean(self.bn2.running_var).cpu().numpy())
        cut = 2*std2
        # Pass it through output layer
        h = torch.tensor(1.8/(4*std2)) * \
            torch.clamp(h, min=-cut, max=cut) + self.conversion_offset
        return self.output_node(h)

    def regularizer(self):
        control_penalty = self.input_node1.regularizer() \
            + self.input_node2.regularizer() \
            + self.output_node.regularizer()
        return control_penalty + self.offset_penalty()

    def offset_penalty(self):
        return torch.sum(torch.relu(self.offset_min - self.offset) + torch.relu(self.offset - self.offset_max))


if __name__ == "__main__":

    import matplotlib.pyplot as plt

    IN_DICT = {}
    IN_DICT['input_node1'] = [3, 4]
    IN_DICT['input_node2'] = [3, 4]
    IN_DICT['hidden_node1'] = [3, 4]
    IN_DICT['hidden_node2'] = [3, 4]
    IN_DICT['output_node'] = [3, 4]

    dnpu_net = DNPU_NET(IN_DICT)
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    dnpu_net.to(device)
    nr_points = 7
    x = -1.2+1.8*np.random.rand(nr_points, 2)
    x = TorchUtils.get_tensor_from_numpy(x)
    target = TorchUtils.get_tensor_from_numpy(
        300 * np.random.rand(nr_points, 1))
    loss = nn.MSELoss()
    optimizer = torch.optim.Adam([{'params': dnpu_net.parameters()}], lr=0.007)

    LOSS_LIST = []
    for eps in range(5000):

        optimizer.zero_grad()
        out = dnpu_net(x)
        if np.isnan(out.data.cpu().numpy()[0]):
            break
        LOSS = loss(out, target) + dnpu_net.regularizer()
        LOSS_LIST.append(LOSS.item())
        print(f'Epoch {eps} with training loss {LOSS_LIST[-1]}')
        LOSS.backward()
        optimizer.step()

    print(f'OUTPUT : \n {out.data.cpu()} \n TARGETS: \n {target.data.cpu()}')

    plt.figure()
    plt.plot(LOSS_LIST)
    plt.title("Loss per epoch")
    plt.show()
