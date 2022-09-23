# -*- coding: utf-8 -*-

import pytorch_lightning as pl
import torch
import torch.nn as nn
from utils import evaluate
from pose_models.pose_resnet import get_pose_net
from utils.pose_resnet_config import cfg
from utils.meter import AverageMeterList
from utils.pck import accuracy
import numpy as np
import os
import torch.nn.functional as F
from net.transformer import ResNetTransformerCls

def _make_deconv_layer(num_layers, num_filters, num_kernels):
    assert num_layers == len(num_filters), \
        'ERROR: num_deconv_layers is different len(num_deconv_filters)'
    assert num_layers == len(num_kernels), \
        'ERROR: num_deconv_layers is different len(num_deconv_filters)'


    inplanes = 2048
    deconv_with_bias = cfg.MODEL.EXTRA.DECONV_WITH_BIAS

    def _get_deconv_cfg(deconv_kernel, index):
        if deconv_kernel == 4:
            padding = 1
            output_padding = 0
        elif deconv_kernel == 3:
            padding = 1
            output_padding = 1
        elif deconv_kernel == 2:
            padding = 0
            output_padding = 0

        return deconv_kernel, padding, output_padding

    layers = []
    for i in range(num_layers):
        kernel, padding, output_padding = \
            _get_deconv_cfg(num_kernels[i], i)

        planes = num_filters[i]
        layers.append(
            nn.ConvTranspose2d(
                in_channels=inplanes,
                out_channels=planes,
                kernel_size=kernel,
                stride=2,
                padding=padding,
                output_padding=output_padding,
                bias=deconv_with_bias))
        layers.append(nn.BatchNorm2d(planes, momentum=0.1))
        layers.append(nn.ReLU(inplace=True))
        inplanes = planes

    return nn.Sequential(*layers)


class PoseResFMNetEgoSTAN(pl.LightningModule):
    def __init__(self, **kwargs):
        super().__init__()

        # parameters
        self.batch_size = kwargs.get("batch_size")
        self.lr = kwargs.get("lr")
        self.es_patience = kwargs.get("es_patience")
        self.which_data = kwargs.get('dataloader')
        self.heatmap_resolution = kwargs.get('heatmap_resolution')
        self.image_resolution = kwargs.get('image_resolution')
        self.seq_len = kwargs.get('seq_len')
        self.dropout = kwargs.get('dropout')
        if self.which_data in ['baseline', 'sequential'] :
            num_class = 16
        elif self.which_data == 'mo2cap2':
            num_class = 15
        elif self.which_data.startswith('h36m'):
            num_class = 17
        

        # must be defined for logging computational graph
        self.example_input_array = torch.rand((1, self.seq_len,3, self.image_resolution[0], self.image_resolution[1]))

        # Generator that produces the HeatMap
        self.model = get_pose_net(cfg, True, use_final=False, deconv=False)
        deconv_transformer = ResNetTransformerCls(in_dim=2048, spatial_dim=8*8, seq_len=self.seq_len*8*8, dim=512, depth=3, heads=8, mlp_dim=1024, dim_head=64, dropout=self.dropout)
        self.deconv_layers = _make_deconv_layer(
                    cfg.MODEL.EXTRA.NUM_DECONV_LAYERS,
                    cfg.MODEL.EXTRA.NUM_DECONV_FILTERS,
                    cfg.MODEL.EXTRA.NUM_DECONV_KERNELS,
                )
        self.final_layer = nn.Conv2d(
                        in_channels=cfg.MODEL.EXTRA.NUM_DECONV_FILTERS[-1],
                        out_channels=cfg.MODEL.NUM_JOINTS,
                        kernel_size=cfg.MODEL.EXTRA.FINAL_CONV_KERNEL,
                        stride=1,
                        padding=1 if cfg.MODEL.EXTRA.FINAL_CONV_KERNEL == 3 else 0
                        )

        # Initialize the mpjpe evaluation pipeline
        self.acc = AverageMeterList(list(range(18)), ":3.2f",  ignore_val=-1)

        # Initialize total validation pose loss
        self.val_loss_hm = torch.tensor(0., device=self.device)

        def weight_init(m):
            """
            Xavier Initialization
            """
            if isinstance(m, torch.nn.Conv2d) or isinstance(m, torch.nn.Linear):
                torch.nn.init.xavier_uniform_(m.weight)
                if m.bias is not None:
                    torch.nn.init.zeros_(m.bias)

        # Initialize weights
        self.apply(weight_init)


        self.iteration = 0
        self.save_hyperparameters()
        self.test_results = {}

    def loss(self, pred, label):
        pred = pred.reshape(pred.size(0), -1)
        label = label.reshape(label.size(0), -1)
        return torch.sum(torch.mean(torch.pow(pred-label, 2), dim=1))


    def configure_optimizers(self):
        """
        Choose what optimizers and learning-rate schedulers to use in your optimization.
        """
        
        optimizer = torch.optim.AdamW(
        self.parameters(), lr=self.lr 
        )
        self.scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer,
            mode='min',
            factor=0.1,
            patience=self.es_patience-3,
            min_lr=1e-8,
            verbose=True)
        
        return optimizer
      

    def forward(self, x):
        """
        Forward pass through model
        :param x: Input image
        :return: 2D heatmap, 16x3 joint inferences, 2D reconstructed heatmap
        """
        # x = 3 x 368 x 368
        dim = x.shape 
        #shape -> batch_size x len_seq x 3 x 368 x 368
        imgs = torch.reshape(x, (dim[0]*dim[1], dim[2], dim[3], dim[4]))
        # imgs = # (batch_size*len_seq) x 3 x 256 x 256

        features = self.model(imgs)

        # features = batch_size*len_seq x 2048 x 8 x 8
        features = features.reshape(dim[0], dim[1], 2048, 8, 8)
        # features = batch_size x len_seq x 2048 x 8 x 8
        features = features.permute(0, 1, 3, 4, 2)
        features = features.reshape(dim[0], -1, 2048)
        # features = batch_size x len_seq*8*8 x 2048
        features, atts = self.transformer(features)
        # features = batch_size x 64 x 2048
        features = features.reshape(dim[0], 8, 8, 2048)
        features = features.permute(0, 3, 1, 2) 
        # features = batch_size x 2048 x 8 x 8

        features = self.deconv_layers(features)
        pred = self.final_layer(features)
        return pred

    def training_step(self, batch, batch_idx):
        """
        Compute and return the training loss
        logging resources:
        https://pytorch-lightning.readthedocs.io/en/latest/starter/introduction_guide.html
        """
        tensorboard = self.logger.experiment
        img, p2d, p3d, action = batch
        img = img.cuda()
        p2d = p2d.cuda()
        p2d = p2d[:, -1, :, :, :]
        
        # forward pass
        pred = self.forward(img)
        loss = self.loss(pred, p2d)
        
        
        self.log('Total HM loss', loss.item())

     
        acc_per_points, avg_acc, cnt, pred = accuracy(pred.detach().cpu().numpy(), p2d.detach().cpu().numpy())
        self.log('Train Accuracy', np.mean(acc_per_points))
        return loss

    def validation_step(self, batch, batch_idx):
        """
        Compute the metrics for validation batch
        validation loop: https://pytorch-lightning.readthedocs.io/en/stable/common/lightning_module.html#hooks
        """
 
        tensorboard = self.logger.experiment
        img, p2d, p3d, action = batch
        img = img.cuda()
        p2d = p2d.cuda()
        p2d = p2d[:, -1, :, :, :]

        pred = self.forward(img)
        if batch_idx == 0:
            img_plot = img[:, -1, :, :, :].clone()
            tensorboard.add_images('Val Pred Heatmap', torch.clip(torch.sum(pred, dim=1, keepdim=True), 0, 1), self.iteration)
            tensorboard.add_images('Val Label Heatmap', torch.clip(torch.sum(p2d, dim=1, keepdim=True), 0, 1), self.iteration)
            tensorboard.add_images('Val Images', img_plot, self.iteration)
        loss = self.loss(pred, p2d)
        acc_per_points, avg_acc, cnt, pred = accuracy(pred.cpu().numpy(), p2d.cpu().numpy())
        
        self.acc.update(acc_per_points, p2d.size(0))

        return loss

    def on_validation_start(self):
        self.acc = AverageMeterList(list(range(18)), ":3.2f",  ignore_val=-1)

    def validation_epoch_end(self, validation_step_outputs):
        self.log('Validation Accuracy', np.mean(self.acc.average()))
        self.log('Validation Loss', torch.mean(torch.stack(validation_step_outputs)))
        self.scheduler.step(torch.mean(torch.stack(validation_step_outputs)))

    def on_test_start(self):
        self.acc = AverageMeterList(list(range(18)), ":3.2f",  ignore_val=-1)

    def test_step(self, batch, batch_idx):

        img, p2d, p3d, action = batch
        img = img.cuda()
        p2d = p2d.cuda()
        p2d = p2d[:, -1, :, :, :]
        
        pred = self.forward(img)

        loss = self.loss(pred, p2d)
        acc_per_points, avg_acc, cnt, pred = accuracy(pred.cpu().numpy(), p2d.cpu().numpy())
        
        self.acc.update(acc_per_points, p2d.size(0))

    def test_epoch_end(self, test_step_outputs):
        self.test_results = self.acc.average()



if __name__ == "__main__":
    pass
