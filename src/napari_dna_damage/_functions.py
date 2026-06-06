import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from csbdeep.utils import normalize
from tifffile import imwrite


def save_img(img, path, cmap="viridis"):
    height, width = img.shape[:2]
    dpi = 100

    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")

    ax.imshow(img, interpolation="nearest", cmap=cmap)
    plt.savefig(path, pad_inches=0)
    plt.close(fig)


def get_nuclei_stardist(img, stardist_model, outputdir):
    labels, _ = stardist_model.predict_instances(normalize(img))
    imwrite(os.path.join(outputdir, "nuclei_labels.tif"), labels)
    return labels

def get_nuclei_cellpose(img, cellpose_model, diameter, outputdir):
    masks, flows, styles, diams = cellpose_model.eval(img, diameter=None)
    imwrite(os.path.join(outputdir, "nuclei_labels.tif"), masks)
    return masks

def get_spots(img, spotiflow_model, outputdir):
    spots, details = spotiflow_model.predict(img, verbose=False)
    np.save(os.path.join(outputdir, "spots.npy"), spots)
    return spots


def extract_features(
    img,
    outputdir,
    nuclei,
    spots,
    nuclei_channel,
    spot_channel,
):
    # Mean nuclei intensity/std
    nuclei_intensities = [
        np.mean(img[nuclei_channel, nuclei == nucleus])
        for nucleus in np.unique(nuclei[nuclei != 0])
    ]
    mean_nuclei_intensity = np.mean(nuclei_intensities) if nuclei_intensities else 0
    std_nuclei_intensity = np.std(nuclei_intensities) if nuclei_intensities else 0

    # Nuclei area
    nuclei_area = np.sum(nuclei != 0)

    # Number of nuclei
    number_of_nuclei = len(np.unique(nuclei[nuclei != 0]))

    spots = np.round(spots).astype(int)
    validated_spots = []
    nuclei_with_spots = []

    for spot in spots:
        if nuclei[spot[0], spot[1]] > 0:
            validated_spots.append(spot)
            nuclei_with_spots.append(nuclei[spot[0], spot[1]])

    # Number of spots
    number_of_spots = len(validated_spots)

    # Mean spots per nuclei
    mean_spots_per_nuclei = (
        number_of_spots / number_of_nuclei if number_of_nuclei > 0 else 0
    )

    # Number of nuclei with spots
    number_of_nuclei_with_spots = len(np.unique(nuclei_with_spots))

    # Number of nuclei without spots
    number_of_nuclei_without_spots = number_of_nuclei - number_of_nuclei_with_spots

    data = {
        "mean_nuclei_intensity": mean_nuclei_intensity,
        "std_nuclei_intensity": std_nuclei_intensity,
        "nuclei_area (pixels)": nuclei_area,
        "number_of_nuclei": number_of_nuclei,
        "number_of_spots": number_of_spots,
        "mean_spots_per_nuclei": mean_spots_per_nuclei,
        "nuclei_with_spots": number_of_nuclei_with_spots,
        "nuclei_without_spots": number_of_nuclei_without_spots,
    }

    return pd.DataFrame([data])
