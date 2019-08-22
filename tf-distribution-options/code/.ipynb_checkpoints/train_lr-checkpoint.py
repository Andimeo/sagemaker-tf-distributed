import argparse
import codecs
import json
import logging
import numpy as np
import os
import re

import tensorflow as tf
import tensorflow.keras.backend as K
from tensorflow.keras.callbacks import TensorBoard, ModelCheckpoint

logging.getLogger().setLevel(logging.INFO)
tf.logging.set_verbosity(tf.logging.ERROR)


import tensorflow as tf
from tensorflow.keras.layers import Activation, Conv2D, Dense, Dropout, Flatten, MaxPooling2D, BatchNormalization
from tensorflow.keras.models import Sequential
from tensorflow.keras.optimizers import Adam, SGD, RMSprop

def get_model(learning_rate, weight_decay, optimizer, momentum, size, mpi=False, hvd=False):
    model = Sequential()
    model.add(Dense(1))

    if optimizer.lower() == 'sgd':
        opt = SGD(lr=learning_rate, decay=weight_decay, momentum=momentum)
    elif optimizer.lower() == 'rmsprop':
        opt = RMSprop(lr=learning_rate, decay=weight_decay)
    else:
        opt = Adam(lr=learning_rate, decay=weight_decay)

    model.compile(loss='mse',
                  optimizer=opt,
                  metrics=['mse'])

    return model

class CustomTensorBoardCallback(TensorBoard):
    def on_batch_end(self, batch, logs=None):
        pass


def save_history(path, history):

    history_for_json = {}
    # transform float values that aren't json-serializable
    for key in list(history.history.keys()):
        if type(history.history[key]) == np.ndarray:
            history_for_json[key] == history.history[key].tolist()
        elif type(history.history[key]) == list:
           if  type(history.history[key][0]) == np.float32 or type(history.history[key][0]) == np.float64:
               history_for_json[key] = list(map(float, history.history[key]))

    with codecs.open(path, 'w', encoding='utf-8') as f:
        json.dump(history_for_json, f, separators=(',', ':'), sort_keys=True, indent=4)


def save_model(model, output):

    # create a TensorFlow SavedModel for deployment to a SageMaker endpoint with TensorFlow Serving
    tf.contrib.saved_model.save_keras_model(model, args.model_dir)
    logging.info("Model successfully saved at: {}".format(output))
    return

def process_input(channel, index):
    if channel == 'train':
        if index == 0:
            X, y =  [[1]], [1]
        else:
            X, y =  [[1]], [3]
    elif channel == 'validation':
        X, y =  [[1]], [4]
    elif channel == 'eval':
        X, y =  [[1]], [4]
    else:
        raise ValueError()
    return np.array(X), np.array(y)

def main(args):

    if 'sourcedir.tar.gz' in args.tensorboard_dir:
        tensorboard_dir = re.sub('source/sourcedir.tar.gz', 'model', args.tensorboard_dir)
    else:
        tensorboard_dir = args.tensorboard_dir

    logging.info("Writing TensorBoard logs to {}".format(tensorboard_dir))

    logging.info("getting data")
    index = args.hosts.index(args.current_host)
    train_dataset = process_input('train', index)
    eval_dataset = process_input('eval', index)
    validation_dataset = process_input('validation', index)

    logging.info("configuring model")
    logging.info("Hosts: "+ os.environ.get('SM_HOSTS'))

    size = len(args.hosts)

    #Deal with this
    model = get_model(args.learning_rate, args.weight_decay, args.optimizer, args.momentum, size)
    callbacks = []
    if args.current_host == args.hosts[0]:
        callbacks.append(ModelCheckpoint(args.output_data_dir + '/checkpoint-{epoch}.h5'))
        callbacks.append(CustomTensorBoardCallback(log_dir=tensorboard_dir))

    logging.info("Starting training")

#    history = model.fit(train_dataset, epochs=args.epochs, validation_data=validation_dataset)

    history = model.fit(x=train_dataset[0],
             y=train_dataset[1],
             steps_per_epoch=10000,# // size,
             epochs=args.epochs,
             validation_data=validation_dataset,
             validation_steps=1,# // size,
             callbacks=callbacks,
             verbose=0)

    score = model.evaluate(eval_dataset[0],
                           eval_dataset[1],
                           steps=1,
                           verbose=0)

    logging.info('host[0]: {}, current_host: {}'.format(args.hosts[0], args.current_host))
    logging.info('Test loss:{}'.format(score[0]))
    logging.info('Test accuracy:{}'.format(score[1]))

    # PS: Save model and history only on worker 0
    if args.current_host == args.hosts[0]:
        save_history(args.model_dir + "/ps_history.p", history)
        save_model(model, args.model_dir)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('--hosts',type=list,default=json.loads(os.environ.get('SM_HOSTS')))
    parser.add_argument('--current-host',type=str,default=os.environ.get('SM_CURRENT_HOST'))
    parser.add_argument('--train',type=str,required=False,default=os.environ.get('SM_CHANNEL_TRAIN'))
    parser.add_argument('--validation',type=str,required=False,default=os.environ.get('SM_CHANNEL_VALIDATION'))
    parser.add_argument('--eval',type=str,required=False,default=os.environ.get('SM_CHANNEL_EVAL'))
    parser.add_argument('--model_dir',type=str,required=True,help='The directory where the model will be stored.')
    parser.add_argument('--model_output_dir',type=str,default=os.environ.get('SM_MODEL_DIR'))
    parser.add_argument('--output_data_dir',type=str,default=os.environ.get('SM_OUTPUT_DATA_DIR'))
    parser.add_argument('--output-dir',type=str,default=os.environ.get('SM_OUTPUT_DIR'))
    parser.add_argument('--tensorboard-dir',type=str,default=os.environ.get('SM_MODULE_DIR'))
    parser.add_argument('--weight-decay',type=float,default=2e-4,help='Weight decay for convolutions.')
    parser.add_argument('--learning-rate',type=float,default=0.001,help='Initial learning rate.')
    parser.add_argument('--epochs',type=int,default=10)
    parser.add_argument('--batch-size',type=int,default=128)
    parser.add_argument('--data-config',type=json.loads,default=os.environ.get('SM_INPUT_DATA_CONFIG'))
    parser.add_argument('--fw-params',type=json.loads,default=os.environ.get('SM_FRAMEWORK_PARAMS'))
    parser.add_argument('--optimizer',type=str,default='adam')
    parser.add_argument('--momentum',type=float,default='0.9')

    args = parser.parse_args()
    logging.info('hosts: %s' % str(args.hosts))
    logging.info('current host: %s' % args.current_host)

    main(args)