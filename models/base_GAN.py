#encoding=utf8
# Copyright (c) 2021 PaddlePaddle Authors. All Rights Reserved.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from copy import deepcopy

import paddle

from .utils.config import BaseConfig, updateConfig
from .loss_criterions import base_loss_criterions
from .loss_criterions.ac_criterion import ACGANCriterion
from .loss_criterions.GDPP_loss import GDPPLoss
from .loss_criterions.gradient_losses import WGANGPGradientPenalty, \
                                             logisticGradientPenalty
from .utils.utils import loadPartOfStateDict, finiteCheck, \
    loadStateDictCompatible


# set device
paddle.set_device('gpu' if paddle.is_compiled_with_cuda() else 'cpu')


class BaseGAN():
    r"""Abstract class: the basic framework for GAN training.
    """

    def __init__(self,
                 dimLatentVector,
                 dimOutput=3,
                 useGPU=True,
                 baseLearningRate=0.001,
                 lossMode='WGANGP',
                 attribKeysOrder=None,
                 weightConditionD=0.0,
                 weightConditionG=0.0,
                 logisticGradReal=0.0,
                 lambdaGP=0.,
                 epsilonD=0.,
                 GDPP=False,
                 **kwargs):
        r"""
        Args:
            dimLatentVector (int): dimension of the latent vector in the model
            dimOutput (int): number of channels of the output image
            useGPU (bool): set to true if the computation should be distribued
                           in the availanle GPUs
            baseLearningRate (float): target learning rate.
            lossMode (string): loss used by the model. Must be one of the
                               following options
                              * 'MSE' : mean square loss.
                              * 'DCGAN': cross entropy loss
                              * 'WGANGP': https://arxiv.org/pdf/1704.00028.pdf
                              * 'Logistic': https://arxiv.org/pdf/1801.04406.pdf
            attribKeysOrder (dict): if not None, activate AC-GAN. In this case,
                                    both the generator and the discrimator are
                                    trained on abelled data.
            weightConditionD (float): in AC-GAN, weight of the classification
                                      loss applied to the discriminator
            weightConditionG (float): in AC-GAN, weight of the classification
                                      loss applied to the generator
            logisticGradReal (float): gradient penalty for the logistic loss
            lambdaGP (float): if > 0, weight of the gradient penalty (WGANGP)
            epsilonD (float): if > 0, penalty on |D(X)|**2
            GDPP (bool): if true activate GDPP loss https://arxiv.org/abs/1812.00068

        """

        if lossMode not in ['MSE', 'WGANGP', 'DCGAN', 'Logistic']:
            raise ValueError(
                "lossMode should be one of the following : ['MSE', 'WGANGP', \
                'DCGAN', 'Logistic']")

        if 'config' not in vars(self):
            self.config = BaseConfig()

        if 'trainTmp' not in vars(self):
            self.trainTmp = BaseConfig()

        self.useGPU = useGPU and paddle.is_compiled_with_cuda()
        if self.useGPU:
            self.device = paddle.get_device()
            self.n_devices = 2
        else:
            self.device = paddle.get_device()
            self.n_devices = 1

        # Latent vector dimension
        self.config.noiseVectorDim = dimLatentVector

        # Output image dimension
        self.config.dimOutput = dimOutput

        # Actual learning rate
        self.config.learningRate = baseLearningRate

        # AC-GAN ?
        self.config.attribKeysOrder = deepcopy(attribKeysOrder)
        self.config.categoryVectorDim = 0
        self.config.weightConditionG = weightConditionG
        self.config.weightConditionD = weightConditionD
        self.ClassificationCriterion = None
        self.initializeClassificationCriterion()

        # GDPP
        self.config.GDPP = GDPP

        self.config.latentVectorDim = self.config.noiseVectorDim \
            + self.config.categoryVectorDim

        # Loss criterion
        self.config.lossCriterion = lossMode
        self.lossCriterion = getattr(
            base_loss_criterions, lossMode)(self.device)

        # WGAN-GP
        self.config.lambdaGP = lambdaGP

        # Weight on D's output
        self.config.epsilonD = epsilonD

        # Initialize the generator and the discriminator
        self.netD = self.getNetD()
        self.netG = self.getNetG()

        # Move the networks to the gpu
        self.updateSolversDevice()

        # Logistic loss
        self.config.logisticGradReal = logisticGradReal


    def test(self, input, getAvG=False, toCPU=True):
        r"""
        Generate some data given the input latent vector.

        Args:
            input (torch.tensor): input latent vector
        """
        if getAvG:
            if toCPU:
                return self.avgG(input).cpu()
            else:
                return self.avgG(input)
        elif toCPU:
            return self.netG(input).detach().cpu()
        else:
            return self.netG(input).detach()

    def buildAvG(self):
        r"""
        Create and upload a moving average generator.
        """
        self.avgG = deepcopy(self.getOriginalG())
        for name, param in self.avgG.named_parameters():
            param.trainable = False

        # if self.useGPU:
        #     self.avgG = paddle.DataParallel(self.avgG)

    def optimizeParameters(self, input_batch, inputLabels=None):
        r"""
        Update the discrimator D using the given "real" inputs.

        Args:
            input (torch.tensor): input batch of real data
            inputLabels (torch.tensor): labels of the real data

        """

        allLosses = {}

        # Retrieve the input data
        self.real_input, self.realLabels = input_batch, None

        if self.config.attribKeysOrder is not None:
            self.realLabels = inputLabels

        n_samples = self.real_input.shape[0]

        # Update the discriminator
        self.optimizerD.clear_grad()

        # #1 Real data
        predRealD = self.netD(self.real_input, False)

        # Classification criterion
        allLosses["lossD_classif"] = \
            self.classificationPenalty(predRealD,
                                       self.realLabels,
                                       self.config.weightConditionD,
                                       backward=True)

        lossD = self.lossCriterion.getCriterion(predRealD, True)
        allLosses["lossD_real"] = lossD.item()

        # #2 Fake data
        inputLatent, targetRandCat = self.buildNoiseData(n_samples)
        predFakeG = self.netG(inputLatent).detach()
        predFakeD = self.netD(predFakeG, False)

        lossDFake = self.lossCriterion.getCriterion(predFakeD, False)
        allLosses["lossD_fake"] = lossDFake.item()
        lossD += lossDFake

        # #3 WGANGP gradient loss
        if self.config.lambdaGP > 0:
            allLosses["lossD_Grad"] = WGANGPGradientPenalty(self.real_input,
                                                            predFakeG,
                                                            self.netD,
                                                            self.config.lambdaGP,
                                                            backward=True)

        # #4 Epsilon loss
        if self.config.epsilonD > 0:
            lossEpsilon = (predRealD[:, 0] ** 2).sum() * self.config.epsilonD
            lossD += lossEpsilon
            allLosses["lossD_Epsilon"] = lossEpsilon.item()


        # # 5 Logistic gradient loss
        if self.config.logisticGradReal > 0:
            allLosses["lossD_logistic"] = \
                logisticGradientPenalty(self.real_input, self.netD,
                                        self.config.logisticGradReal,
                                        backward=True)

        lossD.backward(retain_graph=True)
        finiteCheck(self.getOriginalD().parameters())
        self.optimizerD.step()

        # Logs
        lossD = 0
        for key, val in allLosses.items():

            if key.find("lossD") == 0:
                lossD += val

        allLosses["lossD"] = lossD

        # Update the generator
        self.optimizerG.clear_grad()
        self.optimizerD.clear_grad()

        # #1 Image generation
        inputNoise, targetCatNoise = self.buildNoiseData(n_samples)
        predFakeG = self.netG(inputNoise)

        # #2 Status evaluation
        predFakeD, phiGFake = self.netD(predFakeG, True)

        # #2 Classification criterion
        allLosses["lossG_classif"] = \
            self.classificationPenalty(predFakeD,
                                       targetCatNoise,
                                       self.config.weightConditionG,
                                       backward=True)

        # #3 GAN criterion
        lossGFake = self.lossCriterion.getCriterion(predFakeD, True)
        allLosses["lossG_fake"] = lossGFake.item()
        lossGFake.backward(retain_graph=True)

        if self.config.GDPP:
            _, phiDReal = self.netD.forward(self.real_input, True)
            allLosses["lossG_GDPP"] = GDPPLoss(phiDReal, phiGFake,
                                               backward=True)

        finiteCheck(self.getOriginalG().parameters())
        self.optimizerG.step()

        lossG = 0
        for key, val in allLosses.items():

            if key.find("lossG") == 0:
                lossG += val

        allLosses["lossG"] = lossG

        # Update the moving average if relevant
        for p, avg_p in zip(self.getOriginalG().parameters(), self.getOriginalAvgG().parameters()):
            new_val = avg_p.multiply(paddle.to_tensor(0.999)).add_(
                paddle.to_tensor(0.001) * paddle.to_tensor(p.detach()))
            avg_p.set_value(new_val)

        return allLosses

    def initializeClassificationCriterion(self):
        r"""
        For labelled datasets: initialize the classification criterion.
        """

        if self.config.weightConditionD != 0 and \
                not self.config.attribKeysOrder:
            raise AttributeError("If the weight on the conditional term isn't "
                                 "null, then a attribute dictionnery should be"
                                 " defined")

        if self.config.weightConditionG != 0 and \
                not self.config.attribKeysOrder:
            raise AttributeError("If the weight on the conditional term isn't \
                                 null, then a attribute dictionnary should be \
                                 defined")

        if self.config.attribKeysOrder is not None:
            self.ClassificationCriterion = \
                    ACGANCriterion(self.config.attribKeysOrder)

            self.config.categoryVectorDim = \
                self.ClassificationCriterion.getInputDim()

    def updateSolversDevice(self, buildAvG=True):
        r"""
        Move the current networks and solvers to the GPU.
        This function must be called each time netG or netD is modified
        """
        if buildAvG:
            self.buildAvG()

        # if not isinstance(self.netD, paddle.DataParallel) and self.useGPU:
        #     self.netD = paddle.DataParallel(self.netD)
        # if not isinstance(self.netG, paddle.DataParallel) and self.useGPU:
        #     self.netG = paddle.DataParallel(self.netG)

        # self.netD.to(self.device)
        # self.netG.to(self.device)

        self.optimizerD = self.getOptimizerD()
        self.optimizerG = self.getOptimizerG()

        self.optimizerD.clear_grad()
        self.optimizerG.clear_grad()

    def buildNoiseData(self, n_samples, inputLabels=None):
        r"""
        Build a batch of latent vectors for the generator.

        Args:
            n_samples (int): number of vector in the batch
        """

        inputLatent = paddle.randn((n_samples, self.config.noiseVectorDim))

        if self.config.attribKeysOrder:

            if inputLabels is not None:
                latentRandCat = self.ClassificationCriterion.buildLatentCriterion(inputLabels)
                targetRandCat = inputLabels
            else:
                targetRandCat, latentRandCat = \
                    self.ClassificationCriterion.buildRandomCriterionTensor(n_samples)

            inputLatent = paddle.concat((inputLatent, latentRandCat), axis=1)

            return inputLatent, targetRandCat

        return inputLatent, None

    def buildNoiseDataWithConstraints(self, n, labels):

        constrainPart = \
            self.ClassificationCriterion.generateConstraintsFromVector(n,
                                                                       labels)
        inputLatent = paddle.randn((n, self.config.noiseVectorDim, 1, 1))

        return paddle.concat((inputLatent, constrainPart), axis=1)

    def getOriginalG(self):
        r"""
        Retrieve the original G network. Use this function
        when you want to modify G after the initialization
        """
        # if isinstance(self.netG, paddle.DataParallel):
        #     return self.netG._layers # .module
        return self.netG

    def getOriginalAvgG(self):
        r"""
        Retrieve the original avG network. Use this function
        when you want to modify avG after the initialization
        """
        # if isinstance(self.avgG, paddle.DataParallel):
        #     return self.avgG._layers  # .module
        return self.avgG

    def getOriginalD(self):
        r"""
        Retrieve the original D network. Use this function
        when you want to modify D after the initialization
        """
        # if isinstance(self.netD, paddle.DataParallel):
        #     return self.netD._layers  # .module
        return self.netD

    def getNetG(self):
        r"""
        The generator should be defined here.
        """
        pass

    def getNetD(self):
        r"""
        The discrimator should be defined here.
        """
        pass

    def getOptimizerD(self):
        r"""
        Optimizer of the discriminator.
        """
        pass

    def getOptimizerG(self):
        r"""
        Optimizer of the generator.
        """
        pass

    def getStateDict(self, saveTrainTmp=False):
        r"""
        Get the model's parameters
        """
        # Get the generator's state
        stateG = self.getOriginalG().state_dict()

        # Get the discrimator's state
        stateD = self.getOriginalD().state_dict()

        out_state = {'config': self.config,
                     'netG': stateG,
                     'netD': stateD}

        # Average GAN
        out_state['avgG'] = self.getOriginalAvgG().state_dict()

        if saveTrainTmp:
            out_state['tmp'] = self.trainTmp

        return out_state

    def save(self, path, saveTrainTmp=False):
        r"""
        Save the model at the given location.

        All parameters included in the self.config class will be saved as well.
        Args:
            - path (string): file where the model should be saved
            - saveTrainTmp (bool): set to True if you want to conserve
                                    the training parameters
        """
        paddle.save(self.getStateDict(saveTrainTmp=saveTrainTmp), path)

    def updateConfig(self, config):
        r"""
        Update the object config with new inputs.

        Args:

            config (dict or BaseConfig) : fields of configuration to be updated

            Typically if config = {"learningRate": 0.1} only the learning rate
            will be changed.
        """
        updateConfig(self.config, config)
        self.updateSolversDevice()

    def load(self,
             path="",
             in_state=None,
             loadG=True,
             loadD=True,
             loadConfig=True,
             finetuning=False):
        r"""
        Load a model saved with the @method save() function

        Args:
            - path (string): file where the model is stored
        """

        in_state = paddle.load(path)
        self.load_state_dict(in_state,
                             loadG=loadG,
                             loadD=loadD,
                             loadConfig=True,
                             finetuning=False)

    def load_state_dict(self,
                        in_state,
                        loadG=True,
                        loadD=True,
                        loadConfig=True,
                        finetuning=False):
        r"""
        Load a model saved with the @method save() function

        Args:
            - in_state (dict): state dict containing the model
        """

        # Step one : load the configuration
        if loadConfig:
            updateConfig(self.config, in_state['config'])
            self.lossCriterion = getattr(
                base_loss_criterions, self.config.lossCriterion)(self.device)
            self.initializeClassificationCriterion()

        # Re-initialize G and D with the loaded configuration
        buildAvG = True

        if loadG:
            self.netG = self.getNetG()
            if finetuning:
                loadPartOfStateDict(
                    self.netG, in_state['netG'], ["formatLayer"])
                self.getOriginalG().initFormatLayer(self.config.latentVectorDim)
            else:
                # Replace me by a standard loadStatedict for open-sourcing TODO
                loadStateDictCompatible(self.netG, in_state['netG'])
                if 'avgG' in in_state:
                    print("Average network found !")
                    self.buildAvG()
                    # Replace me by a standard loadStatedict for open-sourcing
                    loadStateDictCompatible(self.getOriginalAvgG(), in_state['avgG'])
                    buildAvG = False

        if loadD:

            self.netD = self.getNetD()
            if finetuning:
                loadPartOfStateDict(
                    self.netD, in_state['netD'], ["decisionLayer"])
                self.getOriginalD().initDecisionLayer(
                    self.lossCriterion.sizeDecisionLayer
                    + self.config.categoryVectorDim)
            else:
                # Replace me by a standard loadStatedict for open-sourcing TODO
                loadStateDictCompatible(self.netD, in_state['netD'])

        elif 'tmp' in in_state.keys():
            self.trainTmp = in_state['tmp']

        # Don't forget to reset the machinery !
        self.updateSolversDevice(buildAvG)

    def classificationPenalty(self, outputD, target, weight, backward=True):
        r"""
        Compute the classification penalty associated with the current
        output

        Args:
            - outputD (tensor): discriminator's output
            - target (tensor): ground truth labels
            - weight (float): weight to give to this loss
            - backward (bool): do we back-propagate the loss ?

        Returns:
            - outputD (tensor): updated discrimator's output
            - loss (float): value of the classification loss
        """

        if self.ClassificationCriterion is not None:
            loss = weight * \
                self.ClassificationCriterion.getCriterion(outputD, target)
            if backward:
                loss.backward(retain_graph=True)

            return loss.item()
        return 0
