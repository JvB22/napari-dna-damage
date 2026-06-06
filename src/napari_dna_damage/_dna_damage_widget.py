import os
from pathlib import Path

import napari
import tifffile
from magicgui.widgets import FileEdit
from napari.qt.threading import thread_worker
from napari.utils.notifications import show_info
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from napari_dna_damage._functions import (
    extract_features,
    get_nuclei_cellpose,
    get_nuclei_stardist,
    get_spots,
)


def create_text_divider(text):
    """Creates a horizontal line divider with text in the middle."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 5, 0, 5)

    left_line = QFrame()
    left_line.setFrameShape(QFrame.Shape.HLine)
    left_line.setFrameShadow(QFrame.Shadow.Sunken)

    label = QLabel(text)

    right_line = QFrame()
    right_line.setFrameShape(QFrame.Shape.HLine)
    right_line.setFrameShadow(QFrame.Shadow.Sunken)

    layout.addWidget(left_line)
    layout.addWidget(label)
    layout.addWidget(right_line)
    return container


@thread_worker(progress={"total": 3, "desc": "DNA-Damage Analysis"})
def analysis_worker(
    img,
    nuclei_ch,
    spot_ch,
    stardist_model,
    cellpose_model,
    diameter,
    model_type,
    spotiflow_model,
    outputdir,
):
    # Segment Nuclei
    if model_type == "StarDist":
        nuclei_labels = get_nuclei_stardist(
            img[nuclei_ch], stardist_model, str(outputdir)
        )
    elif model_type == "CellPose":
        nuclei_labels = get_nuclei_cellpose(
            img[nuclei_ch], cellpose_model, diameter, str(outputdir)
        )
    yield ("nuclei", nuclei_labels)

    # Find Spots
    spots = get_spots(img[spot_ch], spotiflow_model, outputdir)
    yield ("spots", spots)

    # Calculate Features
    features = extract_features(
        img,
        outputdir,
        nuclei_labels,
        spots,
        nuclei_ch,
        spot_ch,
    )
    features.to_csv(os.path.join(outputdir, "features.csv"))
    yield ("features", features)


@thread_worker
def batch_analysis_worker(
    file_paths,
    nuclei_ch,
    spot_ch,
    stardist_model,
    cellpose_model,
    diameter,
    model_type,
    spotiflow_model,
    aggregate_results,
):

    all_features = []
    errors = []
    total = len(file_paths)
    cancelled = False

    for i, path in enumerate(file_paths):
        path = Path(path)
        stem = path.stem
        yield ("file_start", (i, total, stem))

        try:
            img = tifffile.imread(str(path))
            outputdir = path.parent / (stem + "_output")
            outputdir.mkdir(exist_ok=True)

            if model_type == "StarDist":
                nuclei_labels = get_nuclei_stardist(
                    img[nuclei_ch], stardist_model, str(outputdir)
                )
            elif model_type == "CellPose":
                nuclei_labels = get_nuclei_cellpose(
                    img[nuclei_ch], cellpose_model, diameter, str(outputdir)
                )
            spots = get_spots(img[spot_ch], spotiflow_model, str(outputdir))
            features = extract_features(
                img,
                str(outputdir),
                nuclei_labels,
                spots,
                nuclei_ch,
                spot_ch,
            )
            features["source_file"] = stem
            features.to_csv(os.path.join(outputdir, "features.csv"))
            all_features.append(features)

        except Exception as e:
            errors.append((stem, str(e)))
            yield ("file_error", (i, total, stem, str(e)))
            continue

        yield ("file_done", (i, total, stem))

    yield ("batch_complete", (total - len(errors), len(errors)))


class DNADamageWidget(QWidget):
    def __init__(self, napari_viewer: "napari.viewer.Viewer"):
        super().__init__()
        self.viewer = napari_viewer

        # Init stardist, cellpose and spotiflow
        from cellpose import models
        from spotiflow.model import Spotiflow
        from stardist.models import StarDist2D

        self.StarDist2D = StarDist2D
        self.Spotiflow = Spotiflow
        self.CellPose = models

        # Model placeholders
        self.stardist_model = None
        self.spotiflow_model = None
        self.cellpose_model = None

        self._batch_worker = None

        # UI Components
        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)

        # Image layer selection
        self.main_layout.addWidget(create_text_divider("Working Image"))
        self.layer_selector = QComboBox()
        self._reset_layer_choices()
        self.main_layout.addWidget(self.layer_selector)
        self.viewer.layers.events.inserted.connect(self._reset_layer_choices)
        self.viewer.layers.events.removed.connect(self._reset_layer_choices)
        self.layer_selector.currentTextChanged.connect(self._get_and_apply_num_channels)

        # Choose segmentation model
        self.main_layout.addWidget(create_text_divider("Nuclei Segmentation Model"))
        self.model_selector = QComboBox()
        self.model_selector.addItems(["StarDist", "CellPose"])
        self.model_selector.setCurrentText("StarDist")
        self.main_layout.addWidget(self.model_selector)

        self.cellpose_diameter = QLineEdit()
        self.cellpose_diameter.setPlaceholderText("CellPose diameter")
        self.main_layout.addWidget(self.cellpose_diameter)

        # Different channel selectors - these will indicate which channels contain which stainings
        self.main_layout.addWidget(create_text_divider("Channel Selectors"))
        self.main_layout.addWidget(QLabel("Nuclei Channel"))
        self.nuclei_channel_selector = QComboBox()
        self.main_layout.addWidget(self.nuclei_channel_selector)
        self.main_layout.addWidget(QLabel("Spot Channel"))
        self.spot_channel_selector = QComboBox()
        self.main_layout.addWidget(self.spot_channel_selector)

        # Single image analysis
        self.start_analysis_button = QPushButton("Run Analysis (Single Image)")
        self.start_analysis_button.clicked.connect(self._process_image)
        self.main_layout.addWidget(self.start_analysis_button)

        # Batch processing
        self.main_layout.addWidget(create_text_divider("Batch Processing"))
        self.batch_folder_selector = FileEdit(label="Image Folder:", mode="d")
        self.main_layout.addWidget(self.batch_folder_selector.native)

        # File extension filter
        ext_row = QWidget()
        ext_layout = QHBoxLayout(ext_row)
        ext_layout.setContentsMargins(0, 0, 0, 0)
        ext_layout.addWidget(QLabel("File type:"))
        self.extension_selector = QComboBox()
        self.extension_selector.addItems([".tif", ".tiff"])
        ext_layout.addWidget(self.extension_selector)
        self.main_layout.addWidget(ext_row)

        self.scan_batch_button = QPushButton("Scan Folder")
        self.scan_batch_button.clicked.connect(self._scan_batch_folder)
        self.main_layout.addWidget(self.scan_batch_button)

        # File list
        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(150)
        self.main_layout.addWidget(self.file_list)

        # Aggregate results
        self.aggregate_results_checkbox = QCheckBox("Aggregate Results")
        self.aggregate_results_checkbox.setToolTip(
            "Aggregate the results from all files in the batch processing list. Extract all the nuclei and spots results from multiple files and treat them like a single image. Useful when working with tilescans."
        )
        self.main_layout.addWidget(self.aggregate_results_checkbox)

        # Action buttons
        self.action_layout = QHBoxLayout()

        self.run_batch_button = QPushButton("Run Batch Analysis")
        self.run_batch_button.clicked.connect(self._start_batch_analysis)
        self.action_layout.addWidget(self.run_batch_button)

        self.cancel_batch_button = QPushButton("Cancel")
        self.cancel_batch_button.setEnabled(False)
        self.cancel_batch_button.clicked.connect(self._cancel_batch_analysis)
        self.action_layout.addWidget(self.cancel_batch_button)

        self.main_layout.addLayout(self.action_layout)

        self._batch_file_paths = []

        # Stretch
        self.main_layout.addStretch(1)

    def _get_image_layers(self):
        return [
            layer.name
            for layer in self.viewer.layers
            if isinstance(layer, napari.layers.Image)
        ]

    def _reset_layer_choices(self):
        self.layer_selector.clear()
        self.layer_selector.addItems(self._get_image_layers())

    def _get_and_apply_num_channels(self):
        selected_layer = self.layer_selector.currentText()
        if selected_layer is None or selected_layer == "":
            return 0
        try:
            img = self.viewer.layers[selected_layer].data
        except:
            return
        options = range(img.shape[0])
        selectors = [
            self.nuclei_channel_selector,
            self.spot_channel_selector,
        ]
        for selector in selectors:
            previous = (
                int(selector.currentText()) if selector.currentText() != "" else 0
            )
            selector.clear()
            selector.addItems([str(option) for option in options])
            if previous in options:
                selector.setCurrentText(str(previous))

    def _load_stardist_model(self):
        try:
            self.stardist_model = self.StarDist2D.from_pretrained("2D_versatile_fluo")
        except Exception as e:
            raise ValueError(f"Could not load the StarDist model:\n{e}")

    def _load_spotiflow_model(self):
        try:
            self.spotiflow_model = self.Spotiflow.from_pretrained("general")
        except Exception as e:
            raise ValueError(f"Could not load the Spotiflow model:\n{e}")

    def _load_cellpose_model(self):
        try:
            self.cellpose_model = self.CellPose.Cellpose(gpu=True, model_type="cyto3")
        except Exception as e:
            raise ValueError(f"Could not load the CellPose model:\n{e}")

    def _on_worker_yielded(self, data):
        data_type, result = data
        selected_layer = self.layer_selector.currentText()
        if data_type == "nuclei":
            self.viewer.add_labels(result, name=f"{selected_layer}_nuclei_labels")
        elif data_type == "spots":
            self.viewer.add_points(
                result,
                name=f"{selected_layer}_spots",
                face_color="red",
                symbol="ring",
                opacity=0.75,
            )

    def _on_worker_finished(self):
        self.start_analysis_button.setEnabled(True)
        self.start_analysis_button.setText("Run Analysis (Single Image)")
        show_info("DNA damage analysis completed successfully!")

    def _on_worker_errored(self, exception):
        self.start_analysis_button.setEnabled(True)
        self.start_analysis_button.setText("Run Analysis (Single Image)")
        raise exception

    def _process_image(self):
        if (
            self.model_selector.currentText() == "CellPose"
            and self.cellpose_model is None
        ):
            self._load_cellpose_model()
        if (
            self.model_selector.currentText() == "StarDist"
            and self.stardist_model is None
        ):
            self._load_stardist_model()
        if self.spotiflow_model is None:
            self._load_spotiflow_model()

        selected_layer = self.layer_selector.currentText()
        if selected_layer == "":
            self._on_worker_errored(
                ValueError("Please select a valid working image first")
            )

        if self.model_selector.currentText() == "CellPose":
            try:
                diameter = int(self.cellpose_diameter.text())
            except:
                self._on_batch_worker_errored(
                    ValueError("Please enter a valid diameter")
                )
        else:
            diameter = 0

        layer = self.viewer.layers[selected_layer]
        if layer.source and layer.source.path:
            path = Path(layer.source.path)
            outputdir = os.path.join(path.parent, str(path.stem) + "_output")
        else:
            outputdir = QFileDialog.getExistingDirectory(
                self, "Select output directory", ""
            )
            if outputdir == "":
                return

        if not os.path.isdir(outputdir):
            os.mkdir(outputdir)

        img = layer.data
        nuclei_ch = int(self.nuclei_channel_selector.currentText())
        spot_ch = int(self.spot_channel_selector.currentText())

        self.start_analysis_button.setEnabled(False)
        self.start_analysis_button.setText("Analyzing...")

        worker = analysis_worker(
            img,
            nuclei_ch,
            spot_ch,
            self.stardist_model,
            self.cellpose_model,
            diameter,
            self.model_selector.currentText(),
            self.spotiflow_model,
            outputdir,
        )
        worker.yielded.connect(self._on_worker_yielded)
        worker.finished.connect(self._on_worker_finished)
        worker.errored.connect(self._on_worker_errored)
        worker.start()

    def _scan_batch_folder(self):
        folder = Path(self.batch_folder_selector.get_value())
        ext = self.extension_selector.currentText()
        self._batch_file_paths = sorted(folder.glob(f"*{ext}"))

        self.file_list.clear()
        if not self._batch_file_paths:
            self.file_list.addItem(f"No {ext} files found in folder")
            return

        for path in self._batch_file_paths:
            self.file_list.addItem(f"[ ] {path.name}")

    def _on_batch_worker_yielded(self, data):
        data_type, payload = data

        if data_type == "file_start":
            i, total, stem = payload
            self.file_list.item(i).setText(f"[~] {stem}  ({i + 1}/{total})")

        elif data_type == "file_done":
            i, total, stem = payload
            self.file_list.item(i).setText(f"[✓] {stem}")

        elif data_type == "file_error":
            i, total, stem, err = payload
            self.file_list.item(i).setText(f"[x] {stem} — {err[:60]}")

        elif data_type == "batch_complete":
            n_ok, n_err = payload
            show_info(f"Batch complete: {n_ok} succeeded, {n_err} failed.")

    def _on_batch_worker_finished(self):
        self.run_batch_button.setEnabled(True)
        self.run_batch_button.setText("Run Batch Analysis")

        self.cancel_batch_button.setEnabled(False)
        self.cancel_batch_button.setText("Cancel")

        self.start_analysis_button.setEnabled(True)
        self._batch_worker = None

    def _on_batch_worker_errored(self, exception):
        self.run_batch_button.setEnabled(True)
        self.run_batch_button.setText("Run Batch Analysis")
        self.cancel_batch_button.setEnabled(False)
        self.start_analysis_button.setEnabled(True)
        self._batch_worker = None
        raise exception

    def _start_batch_analysis(self):
        if not self._batch_file_paths:
            raise ValueError("Please scan a folder with images first")
        if (
            self.model_selector.currentText() == "CellPose"
            and self.cellpose_model is None
        ):
            self._load_cellpose_model()
        if (
            self.model_selector.currentText() == "StarDist"
            and self.stardist_model is None
        ):
            self._load_stardist_model()
        if self.spotiflow_model is None:
            self._load_spotiflow_model()

        if self.model_selector.currentText() == "CellPose":
            try:
                diameter = int(self.cellpose_diameter.text())
            except:
                self._on_batch_worker_errored(
                    ValueError("Please enter a valid diameter")
                )
        else:
            diameter = 0

        nuclei_ch = int(self.nuclei_channel_selector.currentText())
        spot_ch = int(self.spot_channel_selector.currentText())

        self.run_batch_button.setEnabled(False)
        self.run_batch_button.setText("Running Batch...")
        self.cancel_batch_button.setEnabled(True)
        self.start_analysis_button.setEnabled(False)

        self._batch_worker = batch_analysis_worker(
            [str(p) for p in self._batch_file_paths],
            nuclei_ch,
            spot_ch,
            self.stardist_model,
            self.cellpose_model,
            diameter,
            self.model_selector.currentText(),
            self.spotiflow_model,
            self.aggregate_results_checkbox.isChecked(),
        )
        self._batch_worker.yielded.connect(self._on_batch_worker_yielded)
        self._batch_worker.finished.connect(self._on_batch_worker_finished)
        self._batch_worker.errored.connect(self._on_batch_worker_errored)

        self._batch_worker.aborted.connect(self._on_batch_worker_finished)

        self._batch_worker.start()

    def _cancel_batch_analysis(self):
        if self._batch_worker is not None:
            self.cancel_batch_button.setEnabled(False)
            self.cancel_batch_button.setText("Cancelling...")
            show_info("Stopping batch analysis after the current file finishes...")
            self._batch_worker.quit()
