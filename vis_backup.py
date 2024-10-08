import argparse
import datetime
import os
import pathlib
import pickle
import torch
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from tqdm import tqdm
from utils import evaluate
from base.base_eval import BaseEval
from train import DATALOADER_DIRECTORY, MODEL_DIRECTORY


sns.set_theme(style="whitegrid")




def main():
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--model", required=True, type=str)
    parser.add_argument("--model_checkpoint_file", required=True, type=str)
    parser.add_argument("--dataloader", required=True)
    parser.add_argument("--dataset_test", required=True, type=str)
    parser.add_argument("--batch_size", default=16, type=int)
    parser.add_argument("--output_directory", required=True, type=str)
    parser.add_argument("--cuda", default="cuda", choices=["cuda", "cpu"], type=str)
    parser.add_argument("--heatmap_type", help='Type of 2D ground truth heatmap, Defaults to "baseline"', 
                        default= 'baseline')
    parser.add_argument(
        "--heatmap_resolution",
        help="2D heatmap resolution",
        nargs="*",
        type=int,
        default=[47, 47],
    )
    parser.add_argument(
        "--image_resolution",
        help="Image resolution",
        nargs="*",
        type=int,
        default=[368, 368],
    )
    parser.add_argument("--num_workers", type=int, required=True)
    parser.add_argument(
        "--encoder_type",
        help='Type of encoder for concatenation, Defaults to "branch_concat"',
        default="branch_concat",
    )
    parser.add_argument(
        "--skip",
        help="# of images/frames to skip in between frames",
        default=0,
        type=int,
    )
    parser.add_argument(
        "--seq_len",
        help="# of images/frames input into sequential model",
        default=5,
        type=int,
    )
    parser.add_argument('--dropout', help='Dropout for transformer', type=float, default=0.)

    dict_args = vars(parser.parse_args())

    assert dict_args["dataloader"] in DATALOADER_DIRECTORY
    data_module = DATALOADER_DIRECTORY[dict_args["dataloader"]](**dict_args)
    test_dataloader = data_module.test_dataloader()

    # Initialize model to test
    # assert dict_args["model"] in MODEL_DIRECTORY
    # # model = MODEL_DIRECTORY[dict_args["model"]].load_from_checkpoint(dict_args["model_checkpoint_file"])
    # model = MODEL_DIRECTORY[dict_args["model"]](**dict_args)
    # model = model.load_from_checkpoint(
    #     dict_args["model_checkpoint_file"]
    # )
    # model = model.to(dict_args['cuda'])
    # model.eval()
    # model.freeze()
    # Store results in dict

    # Iterate through each batch to generate visuals
    print("[p] processing batches")


    # Create output directory
    now = datetime.datetime.now().strftime("%m_%d_%H_%M_%S")
    dir_name = dict_args["model"] + "_" + now
    out_dir = os.path.join(dict_args["output_directory"], dir_name)
    os.makedirs(out_dir, exist_ok=True)

    # Save results file
    results_path = os.path.join(out_dir, "results_" + dir_name + ".pkl")
    handpicked_results_path = os.path.join(out_dir, "handpicked_results_" + dir_name)
    # with open(results_path, "wb") as handle:
    #     pickle.dump(results, handle)

    

    for batch in tqdm(test_dataloader):
        img, p2d, p3d, action, img_path, rawp2d = batch
        

        # if len(p3d.size()) == 3:
        #     p3d = p3d.cpu().numpy()
        # else:
        #     p3d = p3d[:, -1, :, :].cpu().numpy()
        
        # img = img.cuda()
        # if dict_args['model'] in ['xregopose_seq_hm_direct', 'xregopose_seq_hm_direct_avg', 'xregopose_global_trans', 'xregopose_seq_hm_direct_slice']:
        #     hms, pose, atts = model(img)
        #     pose = pose.data.cpu().numpy()

            
            
        # elif dict_args['model'] in ['xregopose', 'xregopose_l1']:
        #     hms, pose, ghm = model(img)
        #     pose = pose.data.cpu().numpy()
        # elif dict_args['model'] in ['xregopose_direct']:
        #     hms, pose = model(img)
        #     pose = pose.data.cpu().numpy()
        # elif dict_args['model'] in ['xregopose_seq']:
        #     hms, pose, ghm, atts = model(img)
        #     pose = pose.data.cpu().numpy()
        # else:
        #     raise('Unsupported model type')

        # errors = np.mean(np.sqrt(np.sum(np.power(p3d - pose, 2), axis=2)), axis=1)
        for idx in range(p3d.shape[0]):
            handpicked_results = {}
            if dict_args['dataloader'] == 'sequential':
                filename = pathlib.Path(img_path[-1][idx]).stem
            else:
                filename = pathlib.Path(img_path[idx]).stem
            
            filename = str(filename).replace(".", "_")
            # if filename in evaluate.highest_differences:
            handpicked_results.update(
            {
                filename: {
                    # "gt_pose": p3d[idx],
                    # "pred_pose": pose[idx],
                    "img": img.cpu().numpy()[idx, -1],
                    'p2d': rawp2d[-1][idx].cpu().numpy()
                }
            }
            )
            # results.update(
            #     {
            #         filename: {
            #             # "gt_pose": p3d[idx],
            #             # "pred_pose": pose[idx],
            #             "action": baseeval.eval(None, None, action[idx]),
            #             "full_mpjpe": errors[idx],
            #         }
            #     }
            # )
            with open(os.path.join(dict_args["output_directory"], filename+'.pkl'), "wb") as handle:
                pickle.dump(handpicked_results, handle)



    
    # plot violin
    # violin_path = os.path.join(out_dir, "violin_" + dir_name + ".jpg")
    # plot_violin(results=results, output_file=violin_path)


def get_errors_per_action(results: dict):
    """
    Seperate the full body mpjpe errors generated by action type

    @param results (dict):
        A dict with the mpjpe and action types per image
        {
            "id_1" : {"action": clapping, "full_mpjpe": 0.3},
            "id_2" : {"action": jumping, "full_mpjpe": 0.15},
            ...
        }
    @returns action_mpjpe (dict):
        A dict with keys being actions and a list of 2-element list
        of the corresponding mpjpe errors with the id
        {
            "clapping": [[id_1, 0.3], ...],
            "jumping": [[id_2, 0.15], ...],
            ...
        }
    """
    action_mpjpe = {}

    for key, value in results.items():
        action = value["action"]
        full_mpjpe = value["full_mpjpe"]

        if action in action_mpjpe:
            action_mpjpe[action].append([key, full_mpjpe])
        else:
            action_mpjpe.update({action: [[key, full_mpjpe]]})

    return action_mpjpe


def plot_violin(results: dict, output_file: str):
    """
    Create and save one figure with violin plots per action
    full-body mpjpe errors. Refer to the url for seaborn
    violin plot configurations:
    https://seaborn.pydata.org/generated/seaborn.violinplot.html

    @param results (dict):
        A dict with the mpjpe and action types per image
        {
            "id_1" : {"action": clapping, "full_mpjpe": 0.3},
            "id_2" : {"action": jumping, "full_mpjpe": 0.15},
            ...
        }

    @param output_file (str):
        The file path and name to save the figure. Include
        'jpg' file extension

    """
    pd_data = []

    for key, value in results.items():
        pd_data.append([key, value["action"], value["full_mpjpe"]])
    
    df = pd.DataFrame(pd_data, columns=["id", "action", "full_mpjpe"])
    ax = sns.violinplot(x="action", y="full_mpjpe", data=df, inner="quartile")
    ax.set_xticklabels(ax.get_xticklabels(),rotation=90)
    ax.set_ylabel("MPJPE (mm)")
    # os.makedirs(output_file, exist_ok=True)
    ax.figure.savefig(output_file, bbox_inches = "tight")


def plot_skeleton(poses: list, output_file: str):
    """
    Plot, overlay and save joint skeletons for comparison

    @param poses (list):
        A list of different skeletons to overlay and plot.
        This allows for multiple pose inferences to be
        viewed concurrently. Each item in the list is
        required to have the following information:
        [
            {
                "legend_name": "...",
                "plot_color": "...",
                "pose": < num_joints by 3 array >
            },
            ...
        ]

    @param output_file (str):
        The file path and name to save the figure

    """
    fig = plt.figure(figsize=(16, 9))
    ax = plt.axes(projection="3d")

    BONE_LINKS = [
        [0, 1],
        [1, 2],
        [1, 5],
        [2, 3],
        [3, 4],
        [2, 8],
        [8, 9],
        [9, 10],
        [10, 11],
        [8, 12],
        [5, 12],
        [5, 6],
        [6, 7],
        [12, 13],
        [13, 14],
        [14, 15],
    ]

    for item in poses:
        xs = item["pose"][:, 0]
        ys = item["pose"][:, 1]
        zs = -item["pose"][:, 2]
        # draw bones
        for bone in BONE_LINKS:
            index1, index2 = bone[0], bone[1]
            ax.plot3D(
                [xs[index1], xs[index2]],
                [ys[index1], ys[index2]],
                [zs[index1], zs[index2]],
                linewidth=1,
                color=item["plot_color"],
                label=item["legend_name"],
            )
        # draw joints
        ax.scatter(xs, ys, zs, color=item["plot_color"])

    ax.set_xlim(-1, 1)
    ax.set_ylim(-1, 1)
    ax.set_zlim(-1, 1)
    ax.legend()
    ax.title.set_text(f"{output_file}")
    plt.axis("off")
    fig.tight_layout()
    ax.view_init(elev=27.0, azim=41.0)

    os.makedirs(output_file, exist_ok=True)
    fig.savefig(output_file)
    plt.close()


if __name__ == "__main__":
    main()
