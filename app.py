

from flask import Flask, render_template, request, jsonify
import pandas as pd
import numpy as np
from scipy.optimize import minimize
import random
from itertools import combinations
import random
import csv
from collections import deque
import math


def log_likelihood_rk(params, comparisons, model_names):
    # Log-likelihood for the Rao and Kupper model with ties
    param_dict = dict(zip(model_names, params[:-1]))
    tau = params[-1] # Threshold parameter for ties
    theta = np.exp(tau)

    epsilon = 1e-8 
    log_likelihood = 0
    for _, row in comparisons.iterrows():
        pi = param_dict[row['model_1']]
        pj = param_dict[row['model_2']]
        if row['rating'] == 0:
            log_likelihood += np.log(pi / (pi + theta * pj))
        elif row['rating'] == 1:
            log_likelihood += np.log( pj / (theta * pi + pj))
        elif row['rating'] == 2:
            log_likelihood += np.log((pi * pj * (theta**2 - 1)) / ((pi + theta * pj) * (pj + theta * pi)))
    return -log_likelihood

def fit_models(comparisons):
    # print(len(comparisons))


    models = pd.unique(comparisons[['model_1', 'model_2']].values.ravel('K'))
    initial_params = np.array([1.0] * len(models) + [0.5])  # tau for Rao-Kupper
    # print(initial_params)

    bounds = [(0.01, None)] * len(models) + [(1e-8 , 10)] 
    
    # Fit Rao and Kupper model
    result_rk = minimize(log_likelihood_rk, x0=initial_params, args=(comparisons, models),
                         method='L-BFGS-B', bounds=bounds)
                        #  method='BFGS')
    scores_rk = dict(zip(list(models), result_rk.x))


    return scores_rk 
    # return scores_bs

def rank_models(scores):

    if 'tau' in scores:
        del scores['tau']

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    rankings = {model: rank + 1 for rank, (model, score) in enumerate(sorted_scores)}
    return rankings

def calculate_similarity(v1, v2):
    # Parameter to control the rate of decay, can be adjusted based on specific requirements
    decay_rate = 0.1
    difference = abs(v1['total_score'] - v2['total_score'])
    similarity_index = math.exp(-decay_rate * difference)
    return similarity_index

def calculate_naive_scores(comparisons):

    scores = {}
    
    for _, row in comparisons.iterrows():
        model1 = row['model_1']
        model2 = row['model_2']
        result = row['rating']
        
        if model1 not in scores:
            scores[model1] = 0
        if model2 not in scores:
            scores[model2] = 0
        
        if result == 0: 
            scores[model1] += 1
        elif result == 1:  
            scores[model2] += 1
        elif result == 2: 
            scores[model1] += 0.5
            scores[model2] += 0.5
    
    return scores

app = Flask(__name__)

df  = pd.read_csv(r'videos_all_with_result.csv')

df['image_url'].fillna(0, inplace=True)

ratings = []


model_strengths = {model: [1]*6 for model in df['models'].unique()}
all_combinations = []  

comparisons_by_dimension = {i: pd.DataFrame(columns=['model_1', 'model_2', 'rating']) for i in range(1, 7)}

rank_per_dimension = {i: deque(maxlen=6) for i in range(1, 7)}  
model_strengths_per_dimension = {i: {model: 1 for model in df['models'].unique()} for i in range(1, 7)}

count = {i: 0 for i in range(1, 7)}  


begain_count = 200 
current_group_index = 0
groups_per_batch = 8 
M = 5
N = 5
update_count = groups_per_batch*M  

eval_status_per_dimension = {i: False for i in range(1, 7)}  


combinations_type = 'quality' # 'quality' or 'all'

if combinations_type == 'quality':

    score_columns = ['subject_consistency', 'temporal_flickering', 'motion_smoothness',
                    'dynamic_degree', 'aesthetic_quality', 'imaging_quality', 'overall_consistency']

    df[score_columns] = df[score_columns].apply(lambda x: (x - x.min()) / (x.max() - x.min()))

    df['total_score'] = df[score_columns].sum(axis=1)
    grouped = df.groupby(['prompt', 'image_url'])

    group_combinations = []
    for _, group in grouped:
        videos = group.to_dict('records')
        # model_pairs = combinations(videos, 2)
        # print(videos)
        model_pairs = list(combinations(videos, 2))  
        
        group_similarity = 0
        for v1, v2 in model_pairs:
            similarity_index = calculate_similarity(v1 , v2)
            # similarity_index = abs(v1['total_score'] - v2['total_score'])
            # abs(v1['total_score'] - v2['total_score'])
            group_similarity += similarity_index

        
        # group_combinations.append((group_similarity, videos))
        group_combinations.append((group_similarity, model_pairs))
    # print(model_pairs[0])

    group_combinations.sort(reverse=True, key=lambda x: x[0])
    # print(len(group_combinations))

    all_combinations = []
    for _, pairs in group_combinations:
        # all_combinations.extend(pairs)  # Add all pairs from each group in sorted order

        for pair in pairs:
            all_combinations.append(list(pair))  


elif combinations_type == 'all':
    grouped = df.groupby(['prompt', 'image_url'])
    for _, group in grouped:
        models_list = group['models'].unique()
        model_combinations = list(combinations(models_list, 2))
        for combo in model_combinations:
            combo_videos = group[group['models'].isin(combo)]
            if len(combo_videos) == 2:
                all_combinations.append(combo_videos.to_dict('records'))



def submit_result(ratings,models,pairs_id):
    global comparisons_by_dimension, count, rank_per_dimension,eval_status_per_dimension, model_strengths_per_dimension

    model_1 = models[0]
    model_2 = models[1]

    

    for rating in ratings:


        dimension = rating['dimension']
        # print(dimension)
        rate_value = rating['rating']

        new_result = pd.DataFrame({
            'pairs_id': [pairs_id],
            'model_1': [model_1],
            'model_2': [model_2],
            'rating': [int(rate_value)]
        }, index=[0])

        comparisons_by_dimension[dimension] = pd.concat([comparisons_by_dimension[dimension], new_result], ignore_index=True)
        count[dimension] += 1

        if count[dimension] % update_count == 0:

            scores = fit_models(comparisons_by_dimension[dimension])

            print(f"Updated scores for dimension {dimension}: {scores}")

            model_strengths_per_dimension[dimension].update(scores)

            rankings_per = rank_models(scores)


            rank_per_dimension[dimension].append(rankings_per)

            if len(rank_per_dimension[dimension]) >= N:

                last_five_rankings = list(rank_per_dimension[dimension])[-N:]  

                if all(rank == last_five_rankings[0] for rank in last_five_rankings):
                    eval_status_per_dimension[dimension] = True  
    
                else:
                    eval_status_per_dimension[dimension] = False

            
            count[dimension] = 0 
            get_videos()

    return all(eval_status_per_dimension.values()) 


@app.route('/get_videos', methods=['GET'])
def get_videos():
    global all_combinations, count, begain_count,eval_status_per_dimension, model_strengths_per_dimension, current_group_index, groups_per_batch
    # combination_mode = request.args.get('mode', '2')

    if len(comparisons_by_dimension[1]) < begain_count :
        # print(len(comparisons_by_dimension[1]))

        return jsonify(all_combinations[:begain_count])
    else:
        

        n = 10  # all pairs
        size_of_group = groups_per_batch * n
        total_groups = len(all_combinations) // size_of_group

        if current_group_index >= total_groups:
            current_group_index = 0
        

        start_index = current_group_index * size_of_group
        end_index = start_index + size_of_group
        current_combinations = all_combinations[start_index:end_index]
        

        current_group_index += 1


        selected_combinations = []
        dimension_to_use = next((d for d in eval_status_per_dimension if not eval_status_per_dimension[d]), None)
        # print(dimension_to_use)
        # print(current_combinations)

        if dimension_to_use is None:
            return jsonify([])  
        
        for combo_pair in current_combinations:
            model1 = combo_pair[0]['models']
            model2 = combo_pair[1]['models']
            decay_rate = 0.3  

            strength_diff = abs(model_strengths_per_dimension[dimension_to_use][model1] - model_strengths_per_dimension[dimension_to_use][model2])
            probability_to_keep = math.exp(-decay_rate * strength_diff)  

            if random.random() < probability_to_keep:
                selected_combinations.append(combo_pair)

            # print(selected_combinations)

        return jsonify(selected_combinations)

import csv
import os

def initialize_csv(csv_file, fieldnames):

    if not os.path.isfile(csv_file):
        with open(csv_file, 'w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

def check_existing_row(file_name, pair_id, video_url_1, video_url_2):
    with open(file_name, 'r') as csvfile:
        fieldnames = ['pairs_id','model_1','model_2','video_url_1', 'video_url_2', 'dimension', 'rating']
        reader = csv.DictReader(csvfile, fieldnames=fieldnames)
        for row in reader:
            if row['pairs_id'] == str(pair_id) and row['video_url_1'] == video_url_1 and row['video_url_2'] == video_url_2:
                return True
    return False


@app.route('/rate', methods=['POST'])
def rate():

    rating_info = request.json

    user_id = rating_info.get('user_id')
    
 
    if not user_id:
        return jsonify({'message': 'User ID is required'}), 400
    

    ratings = rating_info['ratings']  
    # print(ratings)
    video_urls = rating_info['video_urls']  
    models = rating_info['models'] 
    pairs_id = rating_info['pairs_id']  

   
    csv_file = f'ratings_{user_id}.csv'
    fieldnames = ['pairs_id','model_1', 'model_2','video_url_1', 'video_url_2', 'dimension', 'rating']
    initialize_csv(csv_file, fieldnames)

    pair_count = sum(1 for row in csv.DictReader(open(csv_file)))  # Existing pairs count
    pair_id = pair_count + 1  # Assign new pair_id


    if check_existing_row(csv_file, pairs_id, video_urls[0], video_urls[1]):
        # Update the corresponding rating values
        with open(csv_file, 'r+', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            rows = list(reader)
            updated = False
            for row in rows:
                if row['pairs_id'] == str(pairs_id) and row['video_url_1'] == video_urls[0] and row['video_url_2'] == video_urls[1]:
                    for rating in ratings:
                        if row['dimension'] == rating['dimension']:
                            row['rating'] = rating['rating']
                            updated = True
            if updated:
                csvfile.seek(0)  # Move file pointer to the beginning
                csvfile.truncate()  # Clear file content
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()  # Write header
                writer.writerows(rows)  # Write updated rows

    else:

        with open(csv_file, 'a', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            for rating in ratings:
                dimension = rating['dimension']
                rating_value = rating['rating']


                row_data = {
                    'pairs_id':pairs_id,
                    'model_1': models[0],
                    'model_2': models[1],
                    'video_url_1': video_urls[0],
                    'video_url_2': video_urls[1],
                    'dimension': dimension,
                    'rating': rating_value
                }
                

                writer.writerow(row_data)

    # update_model_strengths(models[0], models[1], ratings)
                
    down = submit_result(ratings,models,pairs_id)

    if down:

        return jsonify({
            'message': 'The video evaluation is complete',
            'completed_pairs': pair_count,
            'new_pair_id': pair_id
        })
    else:
        return jsonify({
            'message': 'Rating received successfully',
            'completed_pairs': pair_count,
            'new_pair_id': pair_id,
        })



@app.route('/')
def index():

    csv_file = r'videos_all_with_result.csv'
    fieldnames = ['video_url_1', 'video_url_2', 'dimension', 'rating']
    initialize_csv(csv_file, fieldnames)
    return render_template('main.html')

if __name__ == '__main__':

    csv_file = r'videos_all_with_result.csv'
    fieldnames = ['video_url_1', 'video_url_2', 'dimension', 'rating']
    initialize_csv(csv_file, fieldnames)
    app.run(debug=True,host = '0.0.0.0' ,port=80)