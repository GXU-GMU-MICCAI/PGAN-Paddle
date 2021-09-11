# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
import paddle

# set device
paddle.set_device('gpu' if paddle.is_compiled_with_cuda() else 'cpu')


def miniBatchStdDev(x, subGroupSize=4):
    r"""
    Add a minibatch standard deviation channel to the current layer.
    In other words:
        1) Compute the standard deviation of the feature map over the minibatch
        2) Get the mean, over all pixels and all channels of thsi ValueError
        3) expand the layer and cocatenate it with the input

    Args:

        - x (tensor): previous layer
        - subGroupSize (int): size of the mini-batches on which the standard deviation
        should be computed
    """
    size = x.shape
    subGroupSize = min(size[0], subGroupSize)
    if size[0] % subGroupSize != 0:
        subGroupSize = size[0]
    G = int(size[0] / subGroupSize)
    if subGroupSize > 1:
        y = x.reshape((-1, subGroupSize, size[1], size[2], size[3]))
        y = paddle.var(y, 1)
        y = paddle.sqrt(y + 1e-8)
        y = y.reshape((G, -1))
        y = paddle.mean(y, 1).reshape((G, 1))
        y = y.expand((G, size[2]*size[3])).reshape((G, 1, 1, size[2], size[3]))
        y = y.expand((G, subGroupSize, -1, -1, -1))
        y = y.reshape((-1, 1, size[2], size[3]))
    else:
        y = paddle.zeros((x.shape[0], 1, x.shape[2], x.shape[3]))

    return paddle.concat([x, y], axis=1)
