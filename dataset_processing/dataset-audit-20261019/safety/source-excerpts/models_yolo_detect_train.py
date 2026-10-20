130:             sf = sz / max(imgs.shape[2:])  # scale factor
131:             if sf != 1:
132:                 ns = [
133:                     math.ceil(x * sf / self.stride) * self.stride for x in imgs.shape[2:]
134:                 ]  # new shape (stretched to gs-multiple)
135:                 imgs = nn.functional.interpolate(imgs, size=ns, mode="bilinear", align_corners=False)
136:             batch["img"] = imgs
137:         return batch
138: 
139:     def set_model_attributes(self):
140:         """Set model attributes based on dataset information."""
141:         self.model.nc = self.data["nc"]  # attach number of classes to model
142:         self.model.names = self.data["names"]  # attach class names to model
143:         self.model.args = self.args  # attach hyperparameters to model
144: 
145:     def set_model_names_for_load(self, model):
146:         """Set target dataset names before loading weights so cls heads can remap by name."""

183:         """Return a YOLO detection model.
184: 
185:         Args:
186:             cfg (str | dict, optional): Model configuration file path or dictionary.
187:             weights (torch.nn.Module, optional): Pretrained model whose weights are loaded into the new model.
188:             verbose (bool): Whether to display model information.
189: 
190:         Returns:
191:             (DetectionModel): YOLO detection model.
192:         """
193:         model = self.set_model_names_for_load(
194:             DetectionModel(cfg, nc=self.data["nc"], ch=self.data["channels"], verbose=verbose and RANK == -1)
195:         )
196:         if weights:
197:             model.load(weights)
198:         return model
199: 
200:     def get_validator(self):
201:         """Return a DetectionValidator for YOLO model validation."""
