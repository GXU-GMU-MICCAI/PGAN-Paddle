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

import numpy as np
import scipy
import scipy.misc
import imageio
import paddle
from PIL import Image


def make_numpy_grid(arrays_list, gridMaxWidth=2048,
                    imgMinSize=128,
                    interpolation='nearest'):

    # NCWH format
    N, C, W, H = arrays_list.shape

    arrays_list = ((arrays_list + 1.0) * 255.0 / 2.0).astype(np.uint8)

    if C == 1:
        arrays_list = np.reshape(arrays_list, (N, W, H))

    gridMaxWidth = max(gridMaxWidth, W)

    imgSize = max(W, imgMinSize)
    imgHeight = int((float(imgSize) / W) * H)
    nImgsPerRows = min(N, int(gridMaxWidth // imgSize))

    gridWidth = nImgsPerRows * imgSize

    nRows = N // nImgsPerRows
    if N % nImgsPerRows > 0:
        nRows += 1

    gridHeight = nRows * imgHeight
    if C == 1:
        outGrid = np.zeros((gridHeight, gridWidth), dtype='uint8')
    else:
        outGrid = np.zeros((gridHeight, gridWidth, C), dtype='uint8')
    outGrid += 255

    interp = {
        'nearest': Image.NEAREST, 
        'lanczos': Image.LANCZOS, 
        'bilinear': Image.BILINEAR, 
        'bicubic': Image.BICUBIC
    }

    indexImage = 0
    for r in range(nRows):
        for c in range(nImgsPerRows):

            if indexImage == N:
                break

            xStart = c * imgSize
            yStart = r * imgHeight

            img = np.array(arrays_list[indexImage])
            img = Image.fromarray(np.transpose(img, (1,2,0)))

            tmpImage = np.array(img.resize((imgSize, imgHeight), resample=interp[interpolation]))

            if C == 1:
                outGrid[yStart:(yStart + imgHeight),
                        xStart:(xStart + imgSize)] = tmpImage
            else:
                outGrid[yStart:(yStart + imgHeight),
                        xStart:(xStart + imgSize), :] = tmpImage

            indexImage += 1

    return outGrid


def publishTensors(data, out_size_image, caption="", window_token=None, env="main"):
    return None


def publishLoss(*args, **kwargs):
    return None


def publishLinePlot(data, xData, name="", window_token=None, env="main"):
    return None


def publishScatterPlot(data, name="", window_token=None):
    return None


def saveTensor(data, out_size_image, path):

    interpolation = 'nearest'
    if isinstance(out_size_image, tuple):
        out_size_image = out_size_image[0]
    data = paddle.clip(data, min=-1, max=1)
    outdata = make_numpy_grid(
        data.numpy(), imgMinSize=out_size_image, interpolation=interpolation)
    imageio.imwrite(path, outdata)


def delete_env(env_name):
    return None
