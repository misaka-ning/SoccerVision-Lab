118:     def cache_labels(self, path: Path = Path("./labels.cache")) -> dict:
119:         """Cache dataset labels, check images and read shapes.
120: 
121:         This is the shared scanning skeleton for file-based datasets; subclasses customize it through the
122:         `get_label_files`, `get_cache_hash`, `verify_args`, `result_to_label` and `scan_summary` hooks instead of
123:         duplicating this method.
124: 
125:         Args:
126:             path (Path): Path where to save the cache file.
127: 
128:         Returns:
129:             (dict): Dictionary containing cached labels and related information.
130:         """
131:         x = {"labels": []}
132:         nm, nf, ne, nc, msgs = 0, 0, 0, 0, []  # number missing, found, empty, corrupt, messages
133:         desc = f"{self.prefix}Scanning {path.parent / path.stem}..."
134:         total = len(self.im_files)
135:         with ThreadPool(NUM_THREADS) as pool:
136:             func, iterable = self.verify_args()
137:             results = pool.imap(func=func, iterable=iterable)
138:             pbar = TQDM(results, desc=desc, total=total)
139:             for result in pbar:
140:                 label, nm_f, nf_f, ne_f, nc_f, msg = self.result_to_label(result)
141:                 nm += nm_f
142:                 nf += nf_f
143:                 ne += ne_f
144:                 nc += nc_f
145:                 if label is not None:
146:                     x["labels"].append(label)
147:                 if msg:
148:                     msgs.append(msg)
149:                 pbar.desc = f"{desc} {self.scan_summary(nf, nm, ne, nc)}"
150:             pbar.close()
151: 
152:         if msgs:
153:             LOGGER.info("\n".join(msgs))
154:         if nf == 0:
155:             if self.augment:  # training requires labels; unlabeled val splits (e.g. COCO test-dev) only warn
156:                 raise ValueError(f"{self.prefix}No labels found in {path}. {HELP_URL}")
157:             LOGGER.warning(f"{self.prefix}No labels found in {path}. {HELP_URL}")
158:         x["hash"] = self.get_cache_hash()
159:         x["results"] = nf, nm, ne, nc, total
160:         x["msgs"] = msgs  # warnings
161:         if x["labels"]:
162:             save_dataset_cache_file(self.prefix, path, x, DATASET_CACHE_VERSION)
163:         return x
164: 
165:     def get_label_files(self) -> list[str]:
166:         """Return the companion label files for the dataset's images, storing them on the instance.
167: 
168:         Returns:
169:             (list[str]): List of label file paths.
170:         """
171:         self.label_files = img2label_paths(self.im_files)
172:         return self.label_files
173: 
174:     def get_cache_hash(self) -> str:
175:         """Return the hash used to validate a label cache against the current dataset files and scan settings.
176: 
177:         Returns:
178:             (str): Dataset cache hash.
179:         """
180:         # add_polygon_background() class is not a label class, so segment and semantic share one cache
181:         nc = self.data.get("bg_class_idx") or len(self.data["names"])
182:         scan_args = (self.use_keypoints, nc, self.data.get("kpt_shape"), self.single_cls)
183:         return get_hash(self.label_files + self.im_files + [str(scan_args)])
184: 
185:     def scan_summary(self, nf: int, nm: int, ne: int, nc: int) -> str:
186:         """Return a one-line summary of scan counters for progress bars and cache logs.

200:         """Return the per-image verification function and its argument iterable used by `cache_labels`.
201: 
202:         Returns:
203:             (tuple): (verify function, zipped argument iterable) for ThreadPool.imap.
204:         """
205:         nkpt, ndim = self.data.get("kpt_shape", (0, 0))
206:         return verify_image_label, zip(
207:             self.im_files,
208:             self.label_files,
209:             repeat(self.prefix),
210:             repeat(self.use_keypoints),
211:             repeat(self.data.get("bg_class_idx") or len(self.data["names"])),  # label classes, no semantic background
212:             repeat(nkpt),
213:             repeat(ndim),
214:             repeat(self.single_cls),
215:         )
216: 

271:     def _load_or_scan_cache(self, cache_path: Path, cache_hash: str) -> tuple[dict, bool]:
272:         """Load a dataset cache file if it matches the current version and hash, otherwise rescan and rebuild it.
273: 
274:         Args:
275:             cache_path (Path): Path of the cache file.
276:             cache_hash (str): Expected hash of the dataset files.
277: 
278:         Returns:
279:             (tuple): (cache dict, True if a valid existing cache file was loaded).
280:         """
281:         try:
282:             cache, exists = load_dataset_cache_file(cache_path), True  # attempt to load a *.cache file
283:             assert cache["version"] == DATASET_CACHE_VERSION  # matches current version
284:             assert cache["hash"] == cache_hash  # identical hash
285:         except Exception:  # missing, stale, or unreadable (e.g. truncated) cache
286:             cache, exists = self.cache_labels(cache_path), False  # run cache ops
287:         return cache, exists
288: 
289:     def get_labels(self) -> list[dict]:
290:         """Return list of label dictionaries for YOLO training.
291: 
292:         This method loads labels from disk or cache, verifies their integrity, and prepares them for training.
293: 
294:         Returns:
295:             (list[dict]): List of label dictionaries, each containing information about an image and its annotations.
296: 
297:         Raises:
298:             RuntimeError: If no valid images are found.
299:         """
300:         label_files = self.get_label_files()
301:         cache_path = Path(label_files[0]).parent.with_suffix(".cache")
302:         cache, exists = self._load_or_scan_cache(cache_path, self.get_cache_hash())
303: 
304:         # Display cache
305:         nf, nm, ne, nc, n = cache.pop("results")  # found, missing, empty, corrupt, total
306:         if exists and LOCAL_RANK in {-1, 0}:
307:             d = f"Scanning {cache_path}... {self.scan_summary(nf, nm, ne, nc)}"
308:             TQDM(None, desc=self.prefix + d, total=n, initial=n)  # display results
309:             if cache["msgs"]:
310:                 LOGGER.info("\n".join(cache["msgs"]))  # display warnings
311: 
312:         # Read cache
313:         labels = cache["labels"]
314:         if not labels:
315:             issues = "\n  ".join(sorted(set(cache["msgs"]))) or "no error details"
316:             raise RuntimeError(f"No valid images found in {cache_path}.\n  {issues}\n{HELP_URL}")
317:         [cache.pop(k) for k in ("hash", "version", "msgs")]  # remove items
318:         self.im_files = [lb["im_file"] for lb in labels]  # update im_files
319:         self.verify_labels(labels, cache_path)
320:         return labels
321: 
322:     def build_transforms(self, hyp: IterableSimpleNamespace) -> Compose:
323:         """Build and append transforms to the list.
324: 
