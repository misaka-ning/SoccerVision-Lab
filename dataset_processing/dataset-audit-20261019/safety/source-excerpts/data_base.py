189:     def get_img_files(self, img_path: str | list[str]) -> list[str]:
190:         """Read image files from the specified path.
191: 
192:         Args:
193:             img_path (str | list[str]): Path or list of paths to image directories or files.
194: 
195:         Returns:
196:             (list[str]): List of image file paths.
197: 
198:         Raises:
199:             FileNotFoundError: If no images are found or the path doesn't exist.
200:         """
201:         try:
202:             f = []  # image files
203:             for p in img_path if isinstance(img_path, list) else [img_path]:
204:                 p = Path(p)  # os-agnostic
205:                 if p.is_dir():  # dir
206:                     f += glob.glob(str(Path(glob.escape(p)) / "**" / "*.*"), recursive=True)
207:                     # F = list(p.rglob('*.*'))  # pathlib
208:                 elif p.is_file():  # file
209:                     with open(p, encoding="utf-8") as t:
210:                         t = t.read().strip().splitlines()
211:                         parent = str(p.parent) + os.sep
212:                         f += [x.replace("./", parent, 1) if x.startswith("./") else x for x in t]  # local to global
213:                         # F += [p.parent / x.lstrip(os.sep) for x in t]  # local to global (pathlib)
214:                 else:
215:                     raise FileNotFoundError(f"{self.prefix}{p} does not exist")
216:             im_files = sorted(x.replace("/", os.sep) for x in f if x.rpartition(".")[-1].lower() in IMG_FORMATS)
217:             # self.img_files = sorted([x for x in f if x.suffix[1:].lower() in IMG_FORMATS])  # pathlib
218:             assert im_files, f"{self.prefix}No images found in {img_path}. {FORMATS_HELP_MSG}"
219:         except Exception as e:
220:             raise FileNotFoundError(f"{self.prefix}Error loading data from {img_path}\n{HELP_URL}") from e
221:         count = self.fraction if isinstance(self.fraction, int) else max(1, round(len(im_files) * self.fraction))
222:         im_files = im_files[:count] if count < len(im_files) else im_files
223:         check_file_speeds(im_files, prefix=self.prefix)  # check image read speeds
224:         return im_files
225: 
226:     def update_labels(self, include_class: list[int] | None) -> None:
