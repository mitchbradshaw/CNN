import numpy as np
import scipy.io
import glob
import os
import re
import tensorflow as tf
import matplotlib.pyplot as py
from manage_data.load_data import *
from manage_data.peruse_data import *
from manage_data.manage_raw import *
from gramian.gramian_calc import *
from PIL import Image

# based on code from https://www.geeksforgeeks.org/machine-learning/introduction-convolution-neural-network/

def get_dense_output(img_path,plotg=False):
    img = get_image(img_path,plotg)
    conv = conv_layer(img,plotg)
    relu = activation_layer(conv,plotg)
    pool = pooling_layer(relu,plotg)
    flat = flatten_layer(pool)
    dense_output = connected_layer(flat)
    return dense_output

#----------------- input layer
def get_image(image_path,plotg=True):
    image = tf.io.read_file(image_path)
    image = tf.io.decode_jpeg(image, channels=1)  
    image = tf.image.resize(image, [300, 300])
    image = tf.image.convert_image_dtype(image, tf.float32)

    if plotg:
        print("Original Image Shape:", image.shape)

        plt.figure(figsize=(5,5))
        plt.imshow(tf.squeeze(image))
        plt.title("Original Image")
        plt.axis('off')
        plt.show()

    # Add batch dimension
    image = tf.expand_dims(image, axis=0)
    return image

#----------------- convolutional layer
def conv_layer(image,plotg=True):
    # define edge detection filter (Laplacian Kernel) to extract import image features
    kernel = tf.constant([
        [-1, -1, -1],
        [-1,  8, -1],
        [-1, -1, -1]
    ], dtype=tf.float32)

    kernel = tf.reshape(kernel, [3, 3, 1, 1])

    # apply the filter
    conv_output = tf.nn.conv2d(
        input=image,
        filters=kernel,
        strides=1,
        padding='SAME'
    )
    if plotg:
        print("After Convolution Shape:", conv_output.shape)

        plt.figure(figsize=(5,5))
        plt.imshow(tf.squeeze(conv_output))
        plt.title("After Convolution")
        plt.axis('off')
        plt.show()
    return conv_output

#----------------- activation layer
def activation_layer(conv_output,plotg=True):
    relu_output = tf.nn.relu(conv_output)

    if plotg:
        print("After ReLU Shape:", relu_output.shape)

        plt.figure(figsize=(5,5))
        plt.imshow(tf.squeeze(relu_output))
        plt.title("After ReLU Activation")
        plt.axis('off')
        plt.show()

    return relu_output

#----------------- pooling layer
def pooling_layer(relu_output,plotg=True):
    pool_output = tf.nn.max_pool2d(
        input=relu_output,
        ksize=2,
        strides=2,
        padding='SAME'
    )

    if plotg:
        print("After Pooling Shape:", pool_output.shape)

        plt.figure(figsize=(5,5))
        plt.imshow(tf.squeeze(pool_output))
        plt.title("After Max Pooling")
        plt.axis('off')
        plt.show()
    return pool_output

#----------------- flattening
def flatten_layer(pool_output):
    flatten_layer = tf.keras.layers.Flatten()
    flatten_output = flatten_layer(pool_output)

    print("After Flatten Shape:", flatten_output.shape)

    print("First 20 Flattened Values:")
    print(flatten_output.numpy()[0][:20])
    return flatten_output

#----------------- fully-connected layer
def connected_layer(flatten_output):
    dense_layer = tf.keras.layers.Dense(
        units=64,         
        activation='relu' 
    )

    dense_output = dense_layer(flatten_output)

    print("After Fully Connected Layer Shape:", dense_output.shape)
    return dense_output

#----------------- output layer
