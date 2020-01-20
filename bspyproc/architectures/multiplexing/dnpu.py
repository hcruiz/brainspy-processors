'''Author: HC Ruiz Euler and Unai Alegre-Ibarra; 
DNPU based network of devices to solve complex tasks 25/10/2019
'''

import torch
import os
import numpy as np
import torch.nn as nn
from bspyproc.utils.pytorch import TorchUtils
from bspyproc.processors.processor_mgr import get_processor


class DNPUArchitecture(nn.Module):
    def __init__(self, configs):
        # offset min = -0.35 max = 0.7
        # scale min = 0.1 max = 1.5
        # conversion offset = -0.6
        super().__init__()
        self.configs = configs
        self.info = {}
        self.info['smg_configs'] = configs
        # self.conversion_offset = torch.tensor(configs['current_to_voltage']['offset'])
        self.offset = self.init_offset(configs['offset']['min'], configs['offset']['max'])
        self.scale = self.init_scale(configs['scale']['min'], configs['scale']['max'])

    def init_offset(self, offset_min, offset_max):
        offset = offset_min + offset_max * np.random.rand(1, 2)
        offset = TorchUtils.get_tensor_from_numpy(offset)
        return nn.Parameter(offset)

    def init_scale(self, scale_min, scale_max):
        if self.info['smg_configs']['scale']['min'] == 1.0 and self.info['smg_configs']['scale']['max'] == 1.0:
            scale = TorchUtils.get_tensor_from_numpy(np.array([1.0]))
            return scale
        else:
            scale = TorchUtils.get_tensor_from_numpy(scale_min + scale_max * np.random.rand(1))
            return nn.Parameter(scale)

    def offset_penalty(self):
        return torch.sum(torch.relu(self.info['smg_configs']['offset']['min'] - self.offset) + torch.relu(self.offset - self.info['smg_configs']['offset']['max']))

    def scale_penalty(self):
        return torch.sum(torch.relu(self.info['smg_configs']['scale']['min'] - self.scale) + torch.relu(self.scale - self.info['smg_configs']['scale']['max']))

    def batch_norm(self, bn, x1, x2):
        # h = bn(torch.cat((x1, x2), dim=1))
        # std = np.sqrt(bn.running_var.clone().cpu().numpy())
        # return h, std
        return bn(torch.cat((x1, x2), dim=1))

#    def current_to_voltage(self, x, std):
        # Pass it through output layer and clip it to two times the standard deviation
#       cut = 2 * std
#        return torch.tensor(1.8 / (4 * std)) * self.clip(x, cut) + self.conversion_offset
        # torch.save(voltage,'voltage.pt')

    def clip(self, x, clipping_value):
        return torch.clamp(x, min=-clipping_value, max=clipping_value)


class TwoToOneDNPU(DNPUArchitecture):

    def __init__(self, configs):
        pass


class TwoToTwoToOneDNPU(DNPUArchitecture):

    def __init__(self, configs):
        super().__init__(configs)
        self.init_model(configs)
        self.init_clipping_values(configs['waveform']['output_clipping_value'])
        self.bn1 = TorchUtils.format_tensor(nn.BatchNorm1d(2, affine=False))
        self.bn2 = TorchUtils.format_tensor(nn.BatchNorm1d(2, affine=False))
        self.init_current_to_voltage_conversion_variables()
        self.output_path = os.path.join('tmp', 'architecture_debug')

        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)

    def init_current_to_voltage_conversion_variables(self):
        self.std = 1
        self.cut = 2 * self.std
        self.current_to_voltage_conversion_amplitude = (self.min_voltage - self.max_voltage) / (-4 * self.std)
        self.current_to_voltage_conversion_offset = ((((2 * self.std) - 1) / (2 * self.std)) * self.max_voltage) + (self.min_voltage / (2 * self.std))

    def init_model(self, configs):
        self.input_node1 = get_processor(configs)  # DNPU(in_dict['input_node1'], path=path)
        print('Warning: storing data_info  directly and only from input_node1 in the architecture of DNPUs')
        self.info['data_info'] = self.input_node1.info['data_info']
        self.min_voltage = self.input_node1.min_voltage
        self.max_voltage = self.input_node1.max_voltage
        self.input_node2 = get_processor(configs)  # DNPU(in_dict['input_node2'], path=path)

        self.hidden_node1 = get_processor(configs)  # DNPU(in_dict['hidden_node1'], path=path)
        self.hidden_node2 = get_processor(configs)  # DNPU(in_dict['hidden_node2'], path=path)

        self.output_node = get_processor(configs)  # DNPU(in_dict['output_node'], path=path)

    def init_clipping_values(self, base_clipping_value):
        self.input_node1_clipping_value = base_clipping_value * self.input_node1.get_amplification_value()
        self.input_node2_clipping_value = base_clipping_value * self.input_node2.get_amplification_value()
        self.hidden_node1_clipping_value = base_clipping_value * self.hidden_node1.get_amplification_value()
        self.hidden_node2_clipping_value = base_clipping_value * self.hidden_node2.get_amplification_value()
        self.output_node_clipping_value = base_clipping_value * self.output_node.get_amplification_value()

    def forward(self, x):
        # Scale and offset
        x = (self.scale * x) + self.offset
        torch.save(x, os.path.join(self.output_path, 'raw_input.pt'))

        # Clipping and passing data to the first layer
        x = self.process_layer(self.input_node1(x), self.input_node2(x), self.bn1, self.input_node1_clipping_value, self.input_node2_clipping_value, 1)
        x = self.process_layer(self.hidden_node1(x), self.hidden_node2(x), self.bn2, self.hidden_node1_clipping_value, self.hidden_node2_clipping_value, 2)

        return self.output_node(x)

    def regularizer(self):
        control_penalty = self.input_node1.regularizer() \
            + self.input_node2.regularizer() \
            + self.hidden_node1.regularizer() \
            + self.hidden_node2.regularizer() \
            + self.output_node.regularizer()
        return control_penalty + self.offset_penalty() + self.scale_penalty()

    def process_layer(self, x1, x2, bn, clipping_value_1, clipping_value_2, i):
        torch.save(x1[:, 0], os.path.join(self.output_path, 'device_layer_' + str(i) + '_output_0.pt'))
        torch.save(x2[:, 0], os.path.join(self.output_path, 'device_layer_' + str(i) + '_output_1.pt'))

        # Clip values at 400
        x1 = self.clip(x1, clipping_value=clipping_value_1)
        x2 = self.clip(x2, clipping_value=clipping_value_2)
        torch.save(x1[:, 0], os.path.join(self.output_path, 'bn_afterclip_' + str(i) + '_0.pt'))
        torch.save(x2[:, 0], os.path.join(self.output_path, 'bn_afterclip_' + str(i) + '_1.pt'))

        bnx = self.batch_norm(bn, x1, x2)
        torch.save(bnx[:, 0], os.path.join(self.output_path, f'bn_afterbatch_' + str(i) + '_0.pt'))
        torch.save(bnx[:, 1], os.path.join(self.output_path, f'bn_afterbatch_' + str(i) + '_1.pt'))

        bnx = self.current_to_voltage(bnx, self.input_node1.input_indices)  # , std[0])
        # bnx2 = self.current_to_voltage(bnx[:, 1])  # , std[1])

        torch.save(bnx[:, 0], os.path.join(self.output_path, f'bn_aftercv_' + str(i) + '_0.pt'))
        torch.save(bnx[:, 1], os.path.join(self.output_path, f'bn_aftercv_' + str(i) + '_1.pt'))
        return bnx  # torch.cat((bnx[0][:, None], bnx[1][:, None]), dim=1)

    def current_to_voltage(self, x, electrode):
        clipped_input = self.clip(x, self.cut)
        amplified_input = self.current_to_voltage_conversion_amplitude[electrode] * clipped_input
        return amplified_input + self.current_to_voltage_conversion_offset[electrode]

    def reset(self):
        # This function needs to be checked
        self.input_node1.reset()
        self.input_node2.reset()
        self.hidden_node1.reset()
        self.hidden_node2.reset()
        self.output_node.reset()
        self.offset.data.uniform_(self.info['smg_configs']['offset']['min'], self.info['smg_configs']['offset']['max'])
        self.scale = self.init_scale(self.info['smg_configs']['scale']['min'], self.info['smg_configs']['scale']['max'])
        if self.info['smg_configs']['batch_norm']:
            self.bn1 = TorchUtils.format_tensor(nn.BatchNorm1d(2, affine=False))
            self.bn2 = TorchUtils.format_tensor(nn.BatchNorm1d(2, affine=False))

    def get_control_voltages(self):
        w1 = next(self.input_node1.parameters())  # .detach().cpu().numpy()
        w2 = next(self.input_node2.parameters())  # .detach().cpu().numpy()
        w3 = next(self.hidden_node1.parameters())  # .detach().cpu().numpy()
        w4 = next(self.hidden_node2.parameters())  # .detach().cpu().numpy()
        w5 = next(self.output_node.parameters())  # .detach().cpu().numpy()
        return torch.stack([w1, w2, w3, w4, w5]).detach()  # .cpu().numpy()
