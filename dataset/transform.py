# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
# -*- coding: utf-8 -*-
"""
Transformation to apply to the data

@author: Denis Tome'

"""
import torch
import numpy as np
from base import BaseTransform
from utils import config


class ImageTrsf(BaseTransform):
    """Image Transform"""

    def __init__(self, mean=0.5, std=0.5):

        super().__init__()
        self.mean = mean
        self.std = std

    def __call__(self, data):
        """Perform transformation

        Arguments:
            data {dict} -- frame data
        """

        if 'image' not in list(data.keys()):
            return data

        # get image from all data
        img = data['image']

        # channel last to channel first
        img = np.transpose(img, [2, 0, 1])

        # normalization
        mean=[0.485, 0.456, 0.406]
        std=[0.229, 0.224, 0.225]
        img[0, :, :] = (img[0, :, :]-mean[0])/std[0]
        img[1, :, :] = (img[1, :, :]-mean[1])/std[1]
        img[2, :, :] = (img[2, :, :]-mean[2])/std[2]
        img -= self.mean
        img /= self.std
        data.update({'image': img})

        return data


class Joints3DTrsf(BaseTransform):
    """Joint Transform"""

    def __init__(self, jid_to_zero = None):

        super().__init__()
        joint_zeroed = config.transforms.norm

        # Added a parameter to manually specify which joint to subtract from p3d

        if jid_to_zero is None:
            assert joint_zeroed in config.skel.keys()
            self.jid_zeroed = config.skel[joint_zeroed].jid
        else:
            self.jid_zeroed = jid_to_zero

    def __call__(self, data):
        """Perform transformation

        Arguments:
            data {dict} -- frame data
        """

        if 'joints3D' not in list(data.keys()):
            return data

        p3d = data['joints3D']
        joint_zeroed = p3d[self.jid_zeroed][np.newaxis]

        # update p3d
        p3d -= joint_zeroed
        data.update({'joints3D': p3d})

        return data


class ToTensor(BaseTransform):
    """Convert ndarrays to Tensors."""

    def __call__(self, data):
        """Perform transformation

        Arguments:
            data {dict} -- frame data
        """

        keys = list(data.keys())
        for k in keys:
            pytorch_data = torch.from_numpy(data[k]).float()
            data.update({k: pytorch_data})

        return data
