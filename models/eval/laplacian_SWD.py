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

import os
import platform
import json

import numpy as np
import paddle

from ..metrics.laplacian_swd import LaplacianSWDMetric
from ..metrics.ms_ssim import MS_SSIM
from ..utils.utils import printProgressBar
from ..datasets.attrib_dataset import AttribDataset
from ..datasets.hd5 import H5Dataset
from ..utils.utils import getVal, loadmodule, getLastCheckPoint, \
    parse_state_name, getNameAndPackage, saveScore
from ..utils.image_transform import standardTransform

# set device
paddle.set_device('gpu' if paddle.is_compiled_with_cuda() else 'cpu')


def test(parser, visualisation=None):
    parser.add_argument('--selfNoise', action='store_true',
                        help="Compute the inner noise of the dataset")
    kwargs = vars(parser.parse_args())

    # Are all parameters available ?
    name = getVal(kwargs, "name", None)
    if name is None and not kwargs['selfNoise']:
        raise ValueError("You need to input a name")

    module = getVal(kwargs, "module", None)
    if module is None:
        raise ValueError("You need to input a module")

    trainingConfig = getVal(kwargs, "config", None)
    if trainingConfig is None:
        raise ValueError("You need to input a configuration file")

    # Loading the model
    scale = getVal(kwargs, "scale", None)

    if name is not None:
        iter = getVal(kwargs, "iter", None)

        checkPointDir = os.path.join(kwargs["dir"], name)
        checkpointData = getLastCheckPoint(
            checkPointDir, name, scale=scale, iter=iter)

        if checkpointData is None:
            print(scale, iter)
            if scale is not None or iter is not None:
                raise FileNotFoundError("Not checkpoint found for model "
                                        + name + " at directory " + dir +
                                        " for scale " + str(scale) +
                                        " at iteration " + str(iter))
            raise FileNotFoundError(
                "Not checkpoint found for model " + name + " at directory "
                + dir)

        modelConfig, pathModel, _ = checkpointData
        with open(modelConfig, 'rb') as file:
            configData = json.load(file)

        modelPackage, modelName = getNameAndPackage(module)
        modelType = loadmodule(modelPackage, modelName)

        model = modelType(useGPU=True,
                          storeAVG=True,
                          **configData)

        if scale is None or iter is None:
            _, scale, iter = parse_state_name(pathModel)

        print("Checkpoint found at scale %d, iter %d" % (scale, iter))
        model.load(pathModel)

    elif scale is None:
        raise AttributeError("Please provide a scale to compute the noise of \
        the dataset")

    # Building the score instance
    depthPyramid = min(scale, 4)
    SWDMetric = LaplacianSWDMetric(7, 128, depthPyramid)
    ms_ssim = MS_SSIM(data_range=1.)

    # Building the dataset
    with open(trainingConfig, 'rb') as file:
        wholeConfig = json.load(file)

    pathPartition = wholeConfig.get("pathPartition", None)
    partitionValue = wholeConfig.get("partitionValue", None)
    attribDict = wholeConfig.get('pathAttrib', None)
    partitionValue = getVal(kwargs, "partition_value", None)

    # Training dataset properties
    pathDB = wholeConfig["pathDB"]
    size = 2 ** (2 + scale)
    db_transform = standardTransform((size, size))

    if os.path.splitext(pathDB)[1] == '.h5':
        dataset = H5Dataset(pathDB,
                            transform=db_transform,
                            partition_path=pathPartition,
                            partition_value=partitionValue)
    else:
        dataset = AttribDataset(pathdb=pathDB,
                                transform=db_transform,
                                attribDictPath=attribDict)

    batchSize = 16
    num_workers = 2 if platform.system().lower() == 'linux' else 0
    dbLoader = paddle.io.DataLoader(dataset, batch_size=batchSize,
                                    num_workers=num_workers, shuffle=True)

    # Metric parameters
    nImagesSampled = min(len(dataset), 16000)
    maxBatch = nImagesSampled / batchSize

    if kwargs['selfNoise']:

        print("Computing the inner noise of the dataset...")
        loader2 = paddle.io.DataLoader(dataset, batch_size=batchSize,
                                       num_workers=num_workers, shuffle=True)

        for item, data in enumerate(zip(dbLoader, loader2)):

            if item > maxBatch:
                break

            real, fake = data
            SWDMetric.updateWithMiniBatch(real[0], fake[0])
            printProgressBar(item, maxBatch)

    else:

        print("Generating the fake dataset...")
        ms_ssim_score = []
        for item, data in enumerate(dbLoader, 0):

            if item > maxBatch:
                break

            inputsReal, _ = data
            inputFake = model.test(model.buildNoiseData(
                inputsReal.shape[0])[0], toCPU=False, getAvG=True)

            SWDMetric.updateWithMiniBatch(inputFake, inputsReal)
            ms_ssim_score.append(ms_ssim(inputFake, inputsReal).mean().item())
            printProgressBar(item, maxBatch)

    printProgressBar(maxBatch, maxBatch)
    print("Merging the results, please wait it can take some time...")
    score = SWDMetric.getScore()
    ms_ssim_score = np.asarray(ms_ssim_score)

    # Saving the results
    if name is not None:

        outPath = os.path.join(checkPointDir, name + "_swd.json")
        if kwargs['selfNoise']:
            saveScore(outPath, score,
                      scale, "inner noise")
        else:
            saveScore(outPath, score,
                      scale, iter)
        saveScore(outPath, ms_ssim_score.mean(),
                  scale, "MS-SSIM")

    # Now printing the results
    print("")

    resolution = ['resolution '] + \
                 [str(int(size / (2 ** factor))) for factor in range(depthPyramid)]
    resolution[-1] += ' (background)'

    strScores = ['score'] + ["{:10.6f}".format(s) for s in score]
    formatCommand = ' '.join(['{:>16}' for x in range(depthPyramid + 1)])

    print(formatCommand.format(*resolution))
    print(formatCommand.format(*strScores))
    print(f"ms-ssim score   {round(ms_ssim_score.mean(), 6)}")
