For each image that is processed, the plugin will create an outputfolder for the image, containing the results of the analysis. The folder will be named ```{input_image_name}_output```.<br>
The folder will contain the following files:

- nuclei_labels.tif - File containing labels for the nuclei. The background is indicated with a value of 0, while nuclei are labeled using incremental positive integers.
- spots.npy - File containing the coordinates of the detected spots, saved in Numpy format.
- features.csv - A comma-separated values file containing various output features of the original input file. The file contains the following features:
    - mean_nuclei_intensity - Obtained by calculating the mean intensity for each nuclei and dividing by the total number of nuclei.
    - std_nuclei_intensity - Obtained by calculating the mean intensity for each nuclei and taking the standard deviation of the resulting values.
    - nuclei_area (pixels) - The total number of pixels in the image belonging to a nuclei.
    - number_of_nuclei - The total number of nuclei in the image.
    - number_of_spots - The total number of spots in the image.
    - mean_spots_per_nuclei - The average number of spots per nuclei in the image.
    - nuclei_with_spots - The number of nuclei in the image containing spots.
    - nuclei_without_spots - The number of nuclei in the image not containing spots.
    - percentage_nuclei_with_spots - The percentage of nuclei in the image containing spots.
    - percentage_nuclei_without_spots - The percentage of nuclei in the image not containing spots.