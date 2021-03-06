import tensorflow as tf
import numpy as np
from tensorflow.contrib import rnn

class slu_model(object):
    def __init__(self, max_seq_len, intent_dim):
        self.hidden_size = 128
        self.intent_dim = intent_dim # one hot encoding
        self.embedding_dim = 200 # read from glove
        self.total_word = 400001 # total word embedding vectors
        self.max_seq_len = max_seq_len
        self.hist_len = 3
        self.add_variables()
        self.add_placeholders()
        self.add_variables()
        self.build_graph()
        self.add_loss()
        self.add_train_op()
        self.init_embedding()
        self.init_model = tf.global_variables_initializer()

    def init_embedding(self):
        self.init_embedding = self.embedding_matrix.assign(self.read_embedding_matrix)

    def add_variables(self):
        self.embedding_matrix = tf.Variable(tf.truncated_normal([self.total_word, self.embedding_dim]), dtype=tf.float32, name="glove_embedding")

    def add_placeholders(self):
        self.history_intent = tf.placeholder(tf.float32, [None, self.hist_len * 2, self.intent_dim])
        self.tourist_input_intent, self.guide_input_intent = tf.split(self.history_intent, num_or_size_splits=2, axis=1)
        self.history_distance = tf.placeholder(tf.float32, [None, self.hist_len * 2])
        self.tourist_dist, self.guide_dist = tf.split(self.history_distance, num_or_size_splits=2, axis=1)
        self.read_embedding_matrix = tf.placeholder(tf.float32, [self.total_word, self.embedding_dim])
        self.labels = tf.placeholder(tf.float32, [None, self.intent_dim])
        self.current_nl_len = tf.placeholder(tf.int32, [None])
        self.current_nl = tf.placeholder(tf.int32, [None, self.max_seq_len])

    def nl_biRNN(self, history_summary):
        with tf.variable_scope("nl"):
            inputs = tf.nn.embedding_lookup(self.embedding_matrix, self.current_nl) # [batch_size, self.max_seq_len, self.embedding_dim]
            history_summary = tf.expand_dims(history_summary, axis=1)
            replicate_summary = tf.tile(history_summary, [1, self.max_seq_len, 1]) # [batch_size, self.max_seq_len, self.intent_dim]
            concat_input = tf.concat([inputs, replicate_summary], axis=2) # [batch_size, self.max_seq_len, self.intent_dim+self.embedding_dim]
            lstm_fw_cell = rnn.BasicLSTMCell(self.hidden_size)
            lstm_bw_cell = rnn.BasicLSTMCell(self.hidden_size)
            _, final_states = tf.nn.bidirectional_dynamic_rnn(lstm_fw_cell, lstm_bw_cell, concat_input, sequence_length=self.current_nl_len, dtype=tf.float32)
            final_fw = tf.concat(final_states[0], axis=1)
            final_bw = tf.concat(final_states[1], axis=1)
            outputs = tf.concat([final_fw, final_bw], axis=1) # concatenate forward and backward final states
            return outputs

    def attention(self):
        with tf.variable_scope("curent_nl"):
            inputs = tf.nn.embedding_lookup(self.embedding_matrix, self.current_nl) # [batch_size, self.max_seq_len, self.embedding_dim]
            lstm_fw_cell = rnn.BasicLSTMCell(self.hidden_size)
            lstm_bw_cell = rnn.BasicLSTMCell(self.hidden_size)
            _, final_states = tf.nn.bidirectional_dynamic_rnn(lstm_fw_cell, lstm_bw_cell, inputs, sequence_length=self.current_nl_len, dtype=tf.float32)
            final_fw = tf.concat(final_states[0], axis=1)
            final_bw = tf.concat(final_states[1], axis=1)
            nl_outputs = tf.concat([final_fw, final_bw], axis=1) # concatenate forward and backward final states
            nl_outputs = tf.layers.dense(inputs=nl_outputs, units=self.intent_dim, kernel_initializer=tf.random_normal_initializer, bias_initializer=tf.random_normal_initializer)
        
        with tf.variable_scope("history_tourist_rnn"):
            lstm_fw_cell = rnn.BasicLSTMCell(self.hidden_size)
            lstm_bw_cell = rnn.BasicLSTMCell(self.hidden_size)
            _, final_states = tf.nn.bidirectional_dynamic_rnn(lstm_fw_cell, lstm_bw_cell, self.tourist_input_intent, dtype=tf.float32)
            final_fw = tf.concat(final_states[0], axis=1)
            final_bw = tf.concat(final_states[1], axis=1)
            tourist_outputs = tf.concat([final_fw, final_bw], axis=1)
        
        with tf.variable_scope("history_guide_rnn"):
            lstm_fw_cell = rnn.BasicLSTMCell(self.hidden_size)
            lstm_bw_cell = rnn.BasicLSTMCell(self.hidden_size)
            _, final_states = tf.nn.bidirectional_dynamic_rnn(lstm_fw_cell, lstm_bw_cell, self.guide_input_intent, dtype=tf.float32)
            final_fw = tf.concat(final_states[0], axis=1)
            final_bw = tf.concat(final_states[1], axis=1)
            guide_outputs = tf.concat([final_fw, final_bw], axis=1)
        
        normalized_weight = tf.unstack(tf.nn.softmax(tf.reciprocal(tf.concat([tf.reduce_min(self.tourist_dist, axis=1, keep_dims=True), tf.reduce_min(self.guide_dist, axis=1, keep_dims=True)], axis=1))), axis=1)
        tourist_outputs = tf.multiply(tourist_outputs, tf.expand_dims(normalized_weight[0], axis=1))
        guide_outputs = tf.multiply(guide_outputs, tf.expand_dims(normalized_weight[1], axis=1))
        
        tourist_dense = tf.layers.dense(inputs=tf.concat([tourist_outputs, nl_outputs], axis=1), units=1, kernel_initializer=tf.random_normal_initializer, bias_initializer=tf.random_normal_initializer, name="dense_layer")
        guide_dense = tf.layers.dense(inputs=tf.concat([guide_outputs, nl_outputs], axis=1), units=1, kernel_initializer=tf.random_normal_initializer, bias_initializer=tf.random_normal_initializer, name="dense_layer", reuse=True)
        weight = tf.unstack(tf.nn.softmax(tf.concat([tourist_dense, guide_dense], axis=1)), axis=1)
        assert len(weight) == 2
        return tf.add(tf.multiply(tf.expand_dims(weight[0], axis=1), tourist_outputs), tf.multiply(tf.expand_dims(weight[1], axis=1), guide_outputs))
    
    def build_graph(self):
        concat_output = self.attention()
        history_summary = tf.layers.dense(inputs=concat_output, units=self.intent_dim, kernel_initializer=tf.random_normal_initializer, bias_initializer=tf.random_normal_initializer)
        final_output = self.nl_biRNN(history_summary)
        self.output = tf.layers.dense(inputs=final_output, units=self.intent_dim, kernel_initializer=tf.random_normal_initializer, bias_initializer=tf.random_normal_initializer)
        self.intent_output = tf.sigmoid(self.output)

    def add_loss(self):
        self.loss = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(labels=self.labels, logits=self.output))
        
    def add_train_op(self):
        optimizer = tf.train.AdamOptimizer(learning_rate=1e-3)
        self.train_op = optimizer.minimize(self.loss)
