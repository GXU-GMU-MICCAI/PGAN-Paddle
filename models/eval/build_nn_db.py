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
import json

from ..metrics.nn_score import buildFeatureExtractor, saveFeatures
from ..utils.utils import getVal, toStrKey
from ..networks.constant_net import FeatureTransform


def test(parser, visualisation=None):

    parser.add_argument('--size', help="Image size",
                        type=int, dest="size", default=224)
    parser.add_argument('-f', '--featureExtractor', help="Path of the feature \
                        extractor",
                        type=str, dest="featureExtractor")

    kwargs = vars(parser.parse_known_args()[0])

    # Parameters
    configPath = getVal(kwargs, "config", None)
    if configPath is None:
        raise ValueError("You need to input a configuratrion file")

    pathFeatureExtractor = getVal(kwargs, "featureExtractor", None)
    if pathFeatureExtractor is None:
        raise ValueError("You need to input a feature extractor")

    with open(configPath, 'rb') as file:
        wholeConfig = json.load(file)

    # Load the dataset
    pathDB = wholeConfig["pathDB"]
    pathAttrib = wholeConfig.get("pathAttrib", None)
    pathMask = wholeConfig.get("pathDBMask", None)
    pathPartition = wholeConfig.get("pathPartition", None)
    partitionValue = wholeConfig.get("partitionValue", None)

    partitionValue = getVal(kwargs, "partition_value", None)

    model, mean, std = buildFeatureExtractor(pathFeatureExtractor)
    imgTransform = FeatureTransform(mean, std, size=kwargs['size'])

    print("Building the model's feature data")

    pathOutFeatures = os.path.splitext(pathFeatureExtractor)[0] + "_" + \
        os.path.splitext(os.path.basename(pathDB))[0] + \
        "_" + str(kwargs['size']) + \
        toStrKey(partitionValue) + "_features.pkl"

    print("Saving the features at : " + pathOutFeatures)

    saveFeatures(model, imgTransform, pathDB, pathMask,  pathAttrib,
                 pathOutFeatures, pathPartition, partitionValue)

    print("All done")
