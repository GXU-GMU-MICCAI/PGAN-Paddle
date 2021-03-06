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


def buildMaskSplit(noiseGShape,
                   noiseGTexture,
                   categoryVectorDim,
                   attribKeysOrder,
                   attribShift,
                   keySplits=None,
                   mixedNoise=False):
    r"""
    Build a 8bits mask that split a full input latent vector into two
    intermediate latent vectors: one for the shape network and one for the
    texture network.
    """

    # latent vector split
    # Reminder, a latent vector is organized as follow
    # [z1,......, z_N, c_1, ....., c_C]
    # N : size of the noise part
    # C : size of the conditional part (ACGAN)

    # Here we will split the vector in
    # [y1, ..., y_N1, z1,......, z_N2, c_1, ....., c_C]

    N1 = noiseGShape
    N2 = noiseGTexture

    if not mixedNoise:
        maskShape = [1 for x in range(N1)] + [0 for x in range(N2)]
        maskTexture = [0 for x in range(N1)] + [1 for x in range(N2)]
    else:
        maskShape = [1 for x in range(N1 + N2)]
        maskTexture = [1 for x in range(N1 + N2)]

    # Now the conditional part
    # Some conditions apply to the shape, other to the texture, and sometimes
    # to both
    if attribKeysOrder is not None:

        C = categoryVectorDim

        if keySplits is not None:
            maskShape = maskShape + [0 for x in range(C)]
            maskTexture = maskTexture + [0 for x in range(C)]

            for key in keySplits["GShape"]:

                index = attribKeysOrder[key]["order"]
                shift = N1 + N2 + attribShift[index]

                for i in range(shift, shift + len(attribKeysOrder[key]["values"])):
                    maskShape[i] = 1

            for key in keySplits["GTexture"]:

                index = attribKeysOrder[key]["order"]
                shift = N1 + N2 + attribShift[index]
                for i in range(shift, shift + len(attribKeysOrder[key]["values"])):
                    maskTexture[i] = 1
        else:

            maskShape = maskShape + [1 for x in range(C)]
            maskTexture = maskTexture + [1 for x in range(C)]

    return maskShape, maskTexture
