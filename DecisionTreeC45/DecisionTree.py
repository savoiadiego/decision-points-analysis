from DecisionTreeC45.decision_tree_utils import get_split_gain, get_total_threshold, extract_rules_from_leaf
from DecisionTreeC45.Nodes import DecisionNode, LeafNode
from typing import Union
import pandas as pd
import numpy as np


class DecisionTree(object):
    """ Implements a decision tree with C4.5 algorithm """

    def __init__(self, attributes_map, max_depth=7):
        self._nodes = set()
        self._root_node = None
        self.max_depth = max_depth
        # attributes map is a disctionary contianing the type of each attribute in the logs.
        # Must be one of ['categorical', 'boolean', 'continuous']
        for attr_name in attributes_map.keys():
            if not attributes_map[attr_name] in ['continuous', 'categorical', 'boolean']:
                raise Exception('Attribute type not supported')
        self._attributes_map = attributes_map

    def delete_node(self, node) -> None:
        """ Removes a node from the tree's set of nodes and disconnects it from its parent node """
        parent_node = node.get_parent_node()
        if node.get_parent_node() is None:
            raise Exception("Can't delete node {}. Parent node not found".format(node._label))
        parent_node.delete_child(node)
        self._nodes.remove(node)

    def add_node(self, node, parent_node) -> None:
        """ Add a node to the tree's set of nodes and connects it to its parent node """
        node.set_parent_node(parent_node)
        self._nodes.add(node)
        if not parent_node is None:
            parent_node.add_child(node)
        elif node.get_label() == 'root':
            self._root_node = node
        else:
            raise Exception("Can't add node {}. Parent label not present in the tree".format(node._label))

    def _predict(self, row_in, node, predictions_dict) -> dict:
        """ Recursively traverse the tree (given the logs in "row_in") until a leaf node and returns the class distribution """
        if node is None:
            raise Exception("Can't traverse the tree. Node is None")
        attribute = node.get_attribute().split(':')[0]
        # In the attribute is known, only the correspondent child is explored.
        if row_in[attribute] != '?':
            child = node.get_child(row_in[attribute])
            if child is None:
                raise Exception("Can't find child with attribute '{}'".format(attribute))
            if isinstance(child, LeafNode):
                for target in child._classes.keys():
                    if not target in predictions_dict.keys():
                        predictions_dict[target] = [(child._classes[target], sum(child._classes.values()))]
                    else:
                        predictions_dict[target].append((child._classes[target], sum(child._classes.values()))) # info about the leaf classes
                    predictions_dict['total_sum'] += child._classes[target] # total sum is needed for the final probability computation
                return predictions_dict
            else:
                return self._predict(row_in, child, predictions_dict)
        else:
            # In case of unknown attribute, the prediction is spread on every child node.
            for child in node.get_childs():
                if isinstance(child, LeafNode):
                    for target in child._classes.keys():
                        if not target in predictions_dict.keys():
                            predictions_dict[target] = [(child._classes[target], sum(child._classes.values()))]
                        else:
                            predictions_dict[target].append((child._classes[target], sum(child._classes.values()))) # info about the leaf classes
                        predictions_dict['total_sum'] += child._classes[target]
                else:
                    predictions_dict = self._predict(row_in, child, predictions_dict)
            return predictions_dict

    def predict(self, data_in, distribution=False):
        """ Starting from the root, predicts the class corresponding to the features contained in "data_in" """
        attribute = self._root_node.get_attribute().split(":")[0]
        data_in = data_in.fillna('?')
        preds = list()
        # data_in is a pandas DataFrame
        for index, row in data_in.iterrows():
            # Every class will have a list of tuple corresponding to every leaf reached (in case of unknown attribute) 
            #predictions_dict = {k: [] for k in data_in['target'].unique()}
            predictions_dict = {'total_sum': 0}
            #predictions_dict['total_sum'] = 0
            # if attribute is known, only the correspondent child is explored
            if row[attribute] != '?':
                child = self._root_node.get_child(row[attribute])
                if child is None:
                    raise Exception("Can't find child with attribute '{}'".format(attribute))
                if isinstance(child, LeafNode):
                    for target in child._classes.keys():
                        if not target in predictions_dict.keys():
                            predictions_dict[target] = [(child._classes[target], sum(child._classes.values()))]
                        else:
                            predictions_dict[target].append((child._classes[target], sum(child._classes.values()))) # info about the leaf classes
                        predictions_dict['total_sum'] += child._classes[target] # needed for the final probability computation
                    preds.append(predictions_dict)
                else:
                    preds.append(self._predict(row, child, predictions_dict))
            else:
                # if attribute is unknown, the case is spreaded to every child node
                for child in self._root_node.get_childs():
                    if isinstance(child, LeafNode):
                        for target in child._classes.keys():
                            if not target in predictions_dict.keys():
                                predictions_dict[target] = [(child._classes[target], sum(child._classes.values()))]
                            else:
                                predictions_dict[target].append((child._classes[target], sum(child._classes.values()))) # info about the leaf classes
                            predictions_dict['total_sum'] += child._classes[target] # needed for the final probability computation
                    else:
                        # recursive part
                        predictions_dict = self._predict(row, child, predictions_dict)
                preds.append(predictions_dict)
        # probability distribution computation for every prediction required
        out_preds = list() 
        out_distr = list()
        for pred in preds:
            pred_distribution = {k: [] for k in pred.keys() if k != 'total_sum'} 
            for target in pred_distribution.keys():
                cond_prob = 0
                # for every leaf selected in the previous part, containing the considered target class
                for conditional in pred[target]:
                    cond_prob += conditional[0] / pred['total_sum']
                pred_distribution[target] = np.round(cond_prob, 4)
            # select the class with max probability
            out_preds.append(max(pred_distribution, key=pred_distribution.get))
            out_distr.append(pred_distribution)
        # return also the distribution or just the prediction
        if distribution:
            out_func = (out_preds, out_distr)
        else:
            out_func = out_preds

        return out_func

    def get_split(self, data_in) -> Union[float, float, str]:
        """ Compute the best split of the input logs """
        max_gain_ratio = None
        threshold_max_gain_ratio = None
        split_attribute = None
        # if there is only the target column or the aren't logs the split doesn't exist
        if len(data_in['target'].unique()) > 1 and len(data_in) > 0:
            # in order the split to be chosen, its information gain must be at least equal to the mean of all the tests considered 
            tests_examined = {'gain_ratio': list(), 'info_gain': list(),
                    'threshold': list(), 'attribute': list(), 'not_near_trivial_subset': list()}
            for column in data_in.columns:
                # gain ratio and threshold (if exist) for every feature 
                if not column in ['target', 'weight'] and len(data_in[column].unique()) > 1:
                    gain_ratio, info_gain, threshold, are_there_at_least_two = get_split_gain(data_in[[column, 'target', 'weight']], 
                        self._attributes_map[column])
                    tests_examined['gain_ratio'].append(gain_ratio)
                    tests_examined['info_gain'].append(info_gain)
                    tests_examined['threshold'].append(threshold)
                    tests_examined['attribute'].append(column)
                    tests_examined['not_near_trivial_subset'].append(are_there_at_least_two)
            # breakpoint()
            # select the best split
            tests_examined = pd.DataFrame.from_dict(tests_examined)
            mean_info_gain = tests_examined['info_gain'].mean()
            # The best split must have at the least two subset with at least two cases 
            # TODO the above condition should be user dependent
            select_max_gain_ratio = tests_examined[(tests_examined['info_gain'] >= mean_info_gain) & (tests_examined['not_near_trivial_subset'])]
            if len(select_max_gain_ratio) != 0:
                max_gain_ratio_idx = select_max_gain_ratio['gain_ratio'].idxmax()
                max_gain_ratio = select_max_gain_ratio.loc[max_gain_ratio_idx, 'gain_ratio']
                max_gain_ratio_threshold = select_max_gain_ratio.loc[max_gain_ratio_idx, 'threshold']
                split_attribute = select_max_gain_ratio.loc[max_gain_ratio_idx, 'attribute']
            elif len(tests_examined[tests_examined['not_near_trivial_subset']]) != 0:
                select_max_gain_ratio = tests_examined[tests_examined['not_near_trivial_subset']]   # Otherwise 'select_max_gain_ratio' computed before is empty
                max_gain_ratio_idx = select_max_gain_ratio['gain_ratio'].idxmax()
                max_gain_ratio = select_max_gain_ratio.loc[max_gain_ratio_idx, 'gain_ratio']
                max_gain_ratio_threshold = select_max_gain_ratio.loc[max_gain_ratio_idx, 'threshold']
                split_attribute = select_max_gain_ratio.loc[max_gain_ratio_idx, 'attribute']
            else:
                max_gain_ratio = None
                max_gain_ratio_threshold = None
                split_attribute = None
        else:
            max_gain_ratio = None
            max_gain_ratio_threshold = None
            split_attribute = None
            
        return max_gain_ratio, max_gain_ratio_threshold, split_attribute

    def split_node(self, node, data_in, data_total) -> None:
        """ Recurseviley split a node based on "data_in" until some conditions are met and a leaves nodes are added to the tree """ 
        # categorical and boolean arguments can be selected only one time in a "line of succession"
        if not ('<' in node.get_label() or '>' in node.get_label()) and not node.get_label() == 'root': 
            data_in = data_in.copy(deep=True) 
            data_in = data_in.drop(columns=[node.get_label().split()[0]])
        max_gain_ratio, local_threshold, split_attribute = self.get_split(data_in)
        # breakpoint()
        # compute error predicting the most frequent class without splitting
        node_errors = data_in['target'].value_counts().sum() - data_in['target'].value_counts().max()
        # compute percentage
        # TODO directly compute percentage
        node_errors = node_errors / len(data_in)
        # if split attribute does not exist then is a leaf 
        if split_attribute is not None and node.get_level() < self.max_depth:
            child_errors = self.compute_split_error(data_in[[split_attribute, 'target']], local_threshold)
            # compute percentage
            # TODO directly compute percentage
            child_errors = child_errors / len(data_in)
            # if child errors are greater the actual error of the node than the split is useless
            if child_errors >= node_errors:
                # the node (default type "DecisionNode") is "transformed" in a leaf node ("LeafNode" type)
                parent_node = node.get_parent_node()
                if parent_node is None and node.get_label() == 'root':
                    print("Childs error percentage is higher than the root one. Can't find a suitable split of the root node.")
                elif parent_node is None:
                    raise Exception("Can't transform DecisionNode {} in LeafNode: no parent found".format(node.get_label()))
                else:
                #breakpoint()
                    self.delete_node(node)
                    node = LeafNode(dict(data_in.groupby('target')['weight'].sum().round(4)), node.get_label(), node.get_level())
                    self.add_node(node, parent_node)
            else:
                # if the attribute with the greatest gain is continuous than the split is binary
                if self._attributes_map[split_attribute] == 'continuous':
                    # compute global threshold (on the complete dataset) from local one
                    threshold = get_total_threshold(data_total[split_attribute], local_threshold)
                    node.set_attribute('{}:{}'.format(split_attribute, threshold), 'continuous')
                    # create DecisionNode, recursion and add node
                    # Low split
                    low_split_node = DecisionNode('{} <= {}'.format(split_attribute, float(threshold)), node.get_level())
                    self.add_node(low_split_node, node)
                    # the split is computed on the known logs and then weighted on unknown ones
                    data_known = data_in[data_in[split_attribute] != '?']
                    data_unknown = data_in[data_in[split_attribute] == '?']
                    weight_unknown = len(data_known[data_known[split_attribute] <= threshold]) / len(data_known)
                    new_weight = (np.array([weight_unknown] * len(data_unknown)) * np.array(data_unknown['weight'].copy(deep=True))).tolist()
                    new_data_unknown = data_unknown.copy(deep=True)
                    new_data_unknown.loc[:, ['weight']] = new_weight
                    # concat the unknown logs to the known ones, weighted, and pass to the next split
                    new_data_low = pd.concat([data_known[data_known[split_attribute] <= threshold], new_data_unknown], ignore_index=True)
                    self.split_node(low_split_node, new_data_low, data_total)
                    # High split
                    high_split_node = DecisionNode('{} > {}'.format(split_attribute, float(threshold)), node.get_level())
                    self.add_node(high_split_node, node)
                    weight_unknown = len(data_known[data_known[split_attribute] > threshold]) / len(data_known)
                    new_weight = (np.array([weight_unknown] * len(data_unknown)) * np.array(data_unknown['weight'].copy(deep=True))).tolist()
                    new_data_unknown = data_unknown.copy(deep=True)
                    new_data_unknown.loc[:, ['weight']] = new_weight
                    new_data_high = pd.concat([data_known[data_known[split_attribute] > threshold], new_data_unknown], ignore_index=True)
                    self.split_node(high_split_node, new_data_high, data_total)
                else:
                    # if the attribute is categorical or boolean than there is a node for every possible attribute value
                    node.set_attribute(split_attribute, self._attributes_map[split_attribute])
                    data_known = data_in[data_in[split_attribute] != '?']
                    data_unknown = data_in[data_in[split_attribute] == '?']
                    for attr_value in data_known[split_attribute].unique():
                        # create DecisionNode, recursion and add node
                        child_node = DecisionNode('{} = {}'.format(split_attribute, attr_value), node.get_level())
                        self.add_node(child_node, node)
                        # the split is computed on the known logs and then weighted on unknown ones
                        weight_unknown = len(data_known[data_known[split_attribute] == attr_value]) / len(data_known)
                        new_weight = (np.array([weight_unknown] * len(data_unknown)) * np.array(data_unknown['weight'].copy(deep=True))).tolist()
                        new_data_unknown = data_unknown.copy(deep=True)
                        new_data_unknown.loc[:, ['weight']] = new_weight
                        # concat the unknown logs to the known ones, weighted, and pass to the next split
                        new_data = pd.concat([data_known[data_known[split_attribute] == attr_value], new_data_unknown], ignore_index=True)
                        self.split_node(child_node, new_data, data_total)
        else:
            # the node (default type "DecisionNode") is "transformed" in a leaf node ("LeafNode" type)
            parent_node = node.get_parent_node()
            if parent_node is None and node.get_label() == 'root':
                print("The logs are not feasible for fitting a tree. Can't find a suitable split of the root node.")
            elif parent_node is None:
                raise Exception("Can't transform DecisionNode {} in LeafNode: no parent found".format(node.get_label()))
            else:
                self.delete_node(node)
                # the final number of class contained is the sum of the weights of every row with that specific target
                node = LeafNode(dict(data_in.groupby('target')['weight'].sum().round(4)), node.get_label(), node.get_level())
                self.add_node(node, parent_node)

    def compute_split_error(self, data_in, threshold) -> int:
        """ Computes the error made by the split if predicting the most frequent class for every child born after it """
        attr_name = [column for column in data_in.columns if column != 'target'][0]
        attr_type = self._attributes_map[attr_name]
        # if continuous type the split is binary given by th threshold
        if attr_type == 'continuous':
            data_in_unknown = data_in[data_in[attr_name] != '?'].copy()
            data_in_unknown.loc[:, attr_name] = data_in_unknown[attr_name].astype(float).copy()
            #breakpoint()
            split_left = data_in_unknown[data_in_unknown[attr_name] <= threshold].copy()
            # pandas function to count the occurnces of the different value of target
            values_count = split_left['target'].value_counts()
            # errors given by the difference between the sum of all occurrences and the most frequent
            errors_left = values_count.sum() - values_count.max()
            split_right = data_in_unknown[data_in_unknown[attr_name] > threshold].copy()
            values_count = split_right['target'].value_counts()
            errors_right = values_count.sum() - values_count.max()
            total_child_error = errors_left + errors_right
        # if categorical or boolean, there is a child for every possible attribute value
        else:
            total_child_error = 0
            for attr_value in data_in[attr_name].unique():
                split = data_in[data_in[attr_name] == attr_value].copy()
                values_count = split['target'].value_counts()
                total_child_error += values_count.sum() - values_count.max()
        return total_child_error

    def fit(self, data_in) -> None:
        """ Fits the tree on "data_in" """
        root_node = DecisionNode('root', 0)
        self.add_node(root_node, None)
        # add weight to dataset in order to handle unknown values
        data_in['weight'] = [1] * len(data_in)
        data_in = data_in.fillna('?')
        self.split_node(self._root_node, data_in, data_in)

    def get_leaves_nodes(self):
        """ Returns a list of the leaves nodes """
        return [node for node in self._nodes if isinstance(node, LeafNode)]

    def get_nodes(self):
        return self._nodes

    def extract_rules(self) -> dict:
        """ Extracts the rules from the tree, one for each target transition.

        For each leaf node, puts in conjunction all the conditions in the path from the root to the leaf node.
        Then, for each target class, put the conjunctive rules in disjunction.
        """

        rules = dict()
        leaf_nodes = self.get_leaves_nodes()
        for leaf_node in leaf_nodes:
            vertical_rules = extract_rules_from_leaf(leaf_node)

            vertical_rules = ' && '.join(vertical_rules)

            if leaf_node._label_class not in rules.keys():
                rules[leaf_node._label_class] = set()
            rules[leaf_node._label_class].add(vertical_rules)

        for target_class in rules.keys():
            rules[target_class] = ' || '.join(rules[target_class])

        return rules