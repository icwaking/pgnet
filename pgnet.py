#Copyright (C) 2016 Paolo Galeone <nessuno@nerdz.eu>
#
#This Source Code Form is subject to the terms of the Mozilla Public
#License, v. 2.0. If a copy of the MPL was not distributed with this
#file, you can obtain one at http://mozilla.org/MPL/2.0/.
#Exhibit B is not attached; this software is compatible with the
#licenses expressed under Section 1.12 of the MPL v2.
"""
The model is fully convolutional, thus it accepts batch of images of any size and produces
a spatial map of vector.
The degenerate case is when the input size have the same size of the train images. In that case
the output is a (batchsize x)1x1x<num_classes> tensor

Conventions:
    var_: placeholder
"""

import os
import sys
import tensorflow as tf
import freeze_graph
import utils

# network constants
INPUT_SIDE = 192
INPUT_DEPTH = 3
DOWNSAMPLING_FACTOR = 8
KERNEL_SIDE = 3
LAST_KERNEL_SIDE = KERNEL_SIDE
LAST_CONV_STRIDE = 1
FC_NEURONS = 2048

# train constants
BATCH_SIZE = 256
LEARNING_RATE = 1e-5  # Initial learning rate.

# output tensor name
OUTPUT_TENSOR_NAME = "softmax_linear/out"

# name of the collection that holds non trainable
# but required variables for the current model
REQUIRED_NON_TRAINABLES = 'required_vars_collection'


# conv_layer do not normalize its output
def conv_layer(input_x, kernel_shape, padding, strides):
    """Returns the result of:
    ReLU(conv2d(x, kernels, padding=padding, strides) + bias).
    Creates kernels (name=kernel), bias (name=bias) and relates summaries.

    Args:
        x: 4-D input tensor. shape = [batch, height, width, depth]
        kernel_shape: the shape of W, used in convolution as kernels:
                [kernel_height, kernel_width, kernel_depth, num_kernels]
        name: the op name
        padding; "VALID" | "SAME"
        stride: 4-d tensor, like: [1, 2, 2, 1]
    """

    num_kernels = kernel_shape[3]

    kernels = utils.kernels(kernel_shape, "kernels")
    bias = utils.bias([num_kernels], "bias")

    out = tf.nn.relu(
        tf.add(tf.nn.conv2d(
            input_x, kernels, strides=strides, padding=padding),
               bias),
        name="out")
    return out


# eq_conv_layer do normalize its output
def eq_conv_layer(input_x, kernel_side, num_kernels, strides, is_training_):
    """Pads the input with the right amount of zeros.
    Convolve the padded input. In that way every pixel of the input image
    will contribute on average.
    Output WxH = input WxH.
    Args:
        input_x: image batch
        kernel_side: kernel side
        num_kernels: the number of the kernels to learn
        strides: 4d tensor like: [1, stride, stride, 1]
        is_training_: boolean placeholder to enable/disable train changes
    Returns:
        batch_norm(conv_layer(input_padded))
    """

    with tf.variable_scope("eq_conv_layer"):
        kernel_shape = [kernel_side, kernel_side, input_x.get_shape()[3].value,
                        num_kernels]

        # pad the input with the right amount of padding
        pad_amount = int((kernel_side - 1) / 2)
        input_padded = tf.pad(input_x, [[0, 0], [pad_amount, pad_amount],
                                        [pad_amount, pad_amount], [0, 0]],
                              name="input_padded")
        print(input_padded)
        conv = conv_layer(input_padded, kernel_shape, "VALID", strides)

        out = tf.contrib.layers.batch_norm(
            conv,
            decay=0.999,
            center=True,
            scale=True,
            epsilon=0.001,
            activation_fn=None,
            updates_collections=None, # update moving mean and variance in place
            is_training=is_training_,
            reuse=None,
            # create a collections of varialbes to save (moving_mean/variance)
            variables_collections=[REQUIRED_NON_TRAINABLES],
            outputs_collections=None,
            trainable=True,
            scope=None)
        return out


def get(num_classes, images_, keep_prob_, is_training_, train_phase=False):
    """
    Args:
        num_classes: is the number of classes that the network will classify
        images_: is a tensor placeholder with shape [-1, widht, height, depth]
        keep_prob_: dropout probability
        is_training_: placeholder to enable/disable train changes
        train_phase: set it to True when training.

    As the net goes deeper, increase the number of filters (using power of 2
    in order to optimize GPU performance).

    @returns:
        softmax_linear/out: spatial map of output vectors (unscaled)
    """

    # in order to have only the images_ placeholder reqired when using
    # the exported model, override is_training_ is_training when the model
    # is not in the train phase. So the placeholder is not required by the model
    if train_phase is False:
        is_training_ = False

    # 192x192x3
    print(images_)

    num_kernels = 2**7  #128
    with tf.variable_scope(str(num_kernels)):
        with tf.variable_scope("conv1"):
            conv1 = eq_conv_layer(images_, KERNEL_SIDE, num_kernels,
                                  [1, 2, 2, 1], is_training_)
        #output: 96x96x128, filters: (3x3x3)x128
        print(conv1)

        with tf.variable_scope("conv2"):
            conv2 = eq_conv_layer(conv1, KERNEL_SIDE, num_kernels,
                                  [1, 2, 2, 1], is_training_)
        #output: 48x48x128, filters: (3x3x128)x128
        print(conv2)

    num_kernels *= 2  #256
    with tf.variable_scope(str(num_kernels)):
        with tf.variable_scope("conv3"):
            conv3 = eq_conv_layer(conv2, KERNEL_SIDE, num_kernels,
                                  [1, 2, 2, 1], is_training_)

        #output: 24x24x256, filters: (3x3x128)x256
        print(conv3)

        with tf.variable_scope("conv4"):
            conv4 = eq_conv_layer(conv3, KERNEL_SIDE, num_kernels,
                                  [1, 2, 2, 1], is_training_)
        #output: 12x12x256, filters: (3x3x128)x256
        print(conv4)

    num_kernels *= 2  #512
    with tf.variable_scope(str(num_kernels)):
        with tf.variable_scope("conv5"):
            conv5 = eq_conv_layer(conv4, KERNEL_SIDE, num_kernels,
                                  [1, 2, 2, 1], is_training_)
        #output: 6x6x512, filters: (3x3x256)x512
        print(conv5)

        with tf.variable_scope("conv6"):
            conv6 = eq_conv_layer(conv5, KERNEL_SIDE, num_kernels,
                                  [1, 2, 2, 1], is_training_)
        #output: 3x3x512, filters: (3x3x512)x512
        print(conv6)

    # fully convolutional layer
    with tf.variable_scope("fc1"):
        fc1 = conv_layer(
            conv6,
            [LAST_KERNEL_SIDE, LAST_KERNEL_SIDE, num_kernels, FC_NEURONS],
            "VALID", [1, 1, 1, 1])
        # remove dependece from the keep_prob_ placeholder when the model
        # is not in train phase
        if train_phase is False:
            dropout1 = fc1
        else:
            dropout1 = tf.nn.dropout(fc1, keep_prob_, name="dropout")

    print(dropout1)
    # output: 1x1xNUM_NEURONS

    with tf.variable_scope("fc2"):
        fc2 = conv_layer(dropout1, [1, 1, FC_NEURONS, FC_NEURONS], "VALID",
                         [1, 1, 1, 1])
        # output: 1x1xNUM_NEURONS
        # remove dependece from the keep_prob_ placeholder when the model
        # is not in train phase
        if train_phase is False:
            dropout2 = fc2
        else:
            dropout2 = tf.nn.dropout(fc2, keep_prob_, name="dropout")

    print(dropout2)
    # output: 1x1xNUM_NEURONS

    with tf.variable_scope("softmax_linear"):
        out = conv_layer(dropout2, [1, 1, FC_NEURONS, num_classes], "VALID",
                         [1, 1, 1, 1])
    # output: (BATCH_SIZE)x1x1xnum_classes if the input has been properly scaled
    # otherwise is a map
    print(out)

    return out


def loss(logits, labels):
    """
    Args:
        logits: Logits from get().
        labels: Labels from distorted_inputs or inputs(). 1-D tensor of shape [batch_size]

    Returns:
        Loss tensor of type float.
    """

    with tf.variable_scope("loss"):
        # remove dimension of size 1 from logits tensor
        # since logits tensor is: (BATCH_SIZE)x1x1xnum_classes
        # remove dimension in position 1 and 2
        logits = tf.squeeze(logits, [1, 2])
        labels = tf.cast(labels, tf.int64)

        # cross_entropy across the batch
        cross_entropy = tf.nn.sparse_softmax_cross_entropy_with_logits(
            logits, labels, name="cross_entropy_per_example")

        mean_cross_entropy = tf.reduce_mean(
            cross_entropy, name="mean_cross_entropy")
        tf.scalar_summary("loss/mean_cross_entropy", mean_cross_entropy)

    return mean_cross_entropy


def train(loss_op, global_step):
    """
    Creates an Optimizer.
    Args:
        loss_op: loss from loss()
        global_step: integer variable counting the numer of traning steps processed

    Returns:
        train_op: of for training
    """
    # Variables that affect learning rate.
    with tf.variable_scope("train"):
        optimizer = tf.train.AdamOptimizer(LEARNING_RATE)
        # minimizes loss and increments global_step by 1
        minimizer = optimizer.minimize(loss_op, global_step=global_step)

    return minimizer


def variables_to_save(addlist):
    """Create a list of all trained variables and required variables of the model.
    Appends to the list, the addlist passed as argument.

    Args:
        addlist: [list, of, variables, to, save]
    Returns:
        a a list of variables"""

    return tf.trainable_variables() + tf.get_collection_ref(
        REQUIRED_NON_TRAINABLES) + addlist


def define_model(num_classes, train_phase):
    """ define the model with its inputs.
    Use this function to define the model in training and when exporting the model
    in the protobuf format.

    Args:
        num_classes: number of classes
        train_phase: set it to True when defining the model, during train

    Return:
        is_training_: enable/disable training placeholder. Useful for evaluation
        keep_prob_: model dropout placeholder
        images_: input images placeholder
        logits: the model output
    """
    is_training_ = tf.placeholder(tf.bool, shape=[], name="is_training_")
    keep_prob_ = tf.placeholder(tf.float32, shape=[], name="keep_prob_")
    images_ = tf.placeholder(
        tf.float32,
        shape=[None, INPUT_SIDE, INPUT_SIDE, INPUT_DEPTH],
        name="images_")

    # build a graph that computes the logits predictions from the images
    logits = get(num_classes,
                 images_,
                 keep_prob_,
                 is_training_,
                 train_phase=train_phase)
    return is_training_, keep_prob_, images_, logits


def export_model(num_classes, session_dir, input_checkpoint, model_filename):
    """Export model defines the model in a new empty graph.
    Creates a saver for the model.
    Restores the session if exists, otherwise prints an error and returns -1
    Once the session has beeen restored, writes in the session_dir the graphs skeleton
    and creates the model.pb file, that holds the computational graph of the model and
    its inputs.

    Args:
        num_classes: number of classes of the trained model
        session_dir: absolute path of the checkpoint folder
        input_checkpoint: the name of the latest checkpoint (the desidered checkpoint to restore).
                          will look into session_dir/input_checkpoint (eg: session_dir/model-0)
        model_filename: the name of the freezed model
    """
    # if the trained model does not exist
    if not os.path.exists(model_filename):
        # create an empty graph into the CPU because GPU can run OOM
        graph = tf.Graph()
        with graph.as_default(), tf.device('/cpu:0'):
            # inject in the default graph the model structure
            define_model(num_classes, train_phase=False)
            # create a saver, to restore the graph in the session_dir
            saver = tf.train.Saver(tf.all_variables())

            # create a new session
            with tf.Session(config=tf.ConfigProto(
                    allow_soft_placement=True)) as sess:
                try:
                    saver.restore(sess, session_dir + "/" + input_checkpoint)
                except ValueError:
                    print(
                        "[E] Unable to restore from checkpoint",
                        file=sys.stderr)
                    return -1

                # save model skeleton (the empty graph, its definition)
                tf.train.write_graph(
                    graph.as_graph_def(),
                    session_dir,
                    "skeleton.pbtxt",
                    as_text=True)

                freeze_graph.freeze_graph(
                    session_dir + "/skeleton.pbtxt", "", False,
                    session_dir + "/" + input_checkpoint, OUTPUT_TENSOR_NAME,
                    "save/restore_all", "save/Const:0", model_filename, True,
                    "")
    else:
        print("{} already exists. Skipping export_model".format(
            model_filename))
