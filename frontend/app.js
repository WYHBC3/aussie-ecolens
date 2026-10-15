

document.getElementById("apiBaseLabel").textContent = API_BASE_URL;

const loginStatusText = document.getElementById("loginStatusText");
const loginButton = document.getElementById("loginButton");
const logoutButton = document.getElementById("logoutButton");

const uploadFile = document.getElementById("uploadFile");
const uploadButton = document.getElementById("uploadButton");
const uploadOutput = document.getElementById("uploadOutput");
const uploadStatusBadge = document.getElementById("uploadStatusBadge");
const uploadStatusMessage = document.getElementById("uploadStatusMessage");
const uploadStatusDetails = document.getElementById("uploadStatusDetails");

const queryTagsInput = document.getElementById("queryTagsInput");
const searchButton = document.getElementById("searchButton");
const queryOutput = document.getElementById("queryOutput");
const resultsGrid = document.getElementById("resultsGrid");

const queryFileInput = document.getElementById("queryFileInput");
const queryFileButton = document.getElementById("queryFileButton");
const queryFileOutput = document.getElementById("queryFileOutput");
const queryFileDetectionCard = document.getElementById("queryFileDetectionCard");
const queryFileDetectedTags = document.getElementById("queryFileDetectedTags");
const queryFileMatchSummary = document.getElementById("queryFileMatchSummary");

const thumbnailQueryInput = document.getElementById("thumbnailQueryInput");
const thumbnailQueryButton = document.getElementById("thumbnailQueryButton");
const thumbnailQueryOutput = document.getElementById("thumbnailQueryOutput");

const tagFileUrlInput = document.getElementById("tagFileUrl");
const tagNameInput = document.getElementById("tagName");
const tagCountInput = document.getElementById("tagCount");
const tagOperationSelect = document.getElementById("tagOperation");
const editTagsButton = document.getElementById("editTagsButton");
const tagEditOutput = document.getElementById("tagEditOutput");

const deleteFileUrl = document.getElementById("deleteFileUrl");
const deleteMode = document.getElementById("deleteMode");
const deleteButton = document.getElementById("deleteButton");
const deleteOutput = document.getElementById("deleteOutput");

const subscriptionEmailInput = document.getElementById("subscriptionEmail");
const subscriptionTagsInput = document.getElementById("subscriptionTags");
const subscribeButton = document.getElementById("subscribeButton");
const subscriptionOutput = document.getElementById("subscriptionOutput");

const toastContainer = document.getElementById("toastContainer");

const SPECIES_LABELS = {
  bos_taurus: "Bos taurus",
  felis_catus: "Felis catus",
  canis_familiaris: "Canis familiaris",
  sus_scrofa: "Sus scrofa",
  casuarius_casuarius: "Casuarius casuarius",
  alectura_lathami: "Alectura lathami",
  perameles_nasuta: "Perameles nasuta",
  thylogale_stigmatica: "Thylogale stigmatica",
};

const MEDIA_TAG_LABELS = {
  image_file: "Image file",
  video_file: "Video file",
  media_file: "Media file",
};

const PRIMARY_MEDIA_BUCKET = "a2-group92-p2-media-909774767032";

function apiUrl(path) {
  if (path?.startsWith("http://") || path?.startsWith("https://")) {
    return path;
  }

  return `${API_BASE_URL}${path}`;
}

function showJson(element, data, isError = false, message = "Response received.", status = "") {
  const outputStatus = status || (isError ? "error" : "success");
  element.classList.remove("empty", "success", "error", "warning");
  element.classList.add(outputStatus);
  element.innerHTML = "";

  const messageElement = document.createElement("p");
  messageElement.className = "output-message";
  messageElement.textContent = message;

  const details = document.createElement("details");
  details.className = "raw-response";

  const summary = document.createElement("summary");
  summary.textContent = isError ? "Technical Details" : "Raw Response";

  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(data, null, 2);

  details.append(summary, pre);
  element.append(messageElement, details);
}

function showMessage(element, message, isError = false) {
  element.classList.remove("empty", "success", "error", "warning");
  element.classList.add(isError ? "error" : "success");
  element.textContent = message;
}

function createRawResponseDetails(data, summaryText = "Raw Response") {
  const details = document.createElement("details");
  details.className = "raw-response";

  const summary = document.createElement("summary");
  summary.textContent = summaryText;

  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(data, null, 2);

  details.append(summary, pre);
  return details;
}

function showToast(message, type = "info") {
  const allowedTypes = ["success", "error", "warning", "info"];
  const toastType = allowedTypes.includes(type) ? type : "info";
  const toast = document.createElement("div");
  toast.className = `toast toast-${toastType}`;
  toast.setAttribute("role", "status");

  const messageElement = document.createElement("span");
  messageElement.textContent = message;

  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.className = "toast-close";
  closeButton.setAttribute("aria-label", "Close notification");
  closeButton.textContent = "×";

  const removeToast = () => {
    toast.classList.add("toast-leaving");
    window.setTimeout(() => toast.remove(), 180);
  };

  closeButton.addEventListener("click", removeToast);
  toast.append(messageElement, closeButton);
  toastContainer.appendChild(toast);

  window.setTimeout(removeToast, 4000);
}

function getErrorToastMessage(error, fallbackMessage) {
  if (error?.status === 401) {
    return "Session expired. Please log in again.";
  }

  const message = error?.data?.error || error?.data?.message || error?.message || "";
  if (message.toLowerCase().includes("invalid json body")) {
    return "Upload request format is not accepted by the API.";
  }

  return fallbackMessage;
}

function showErrorOutput(element, error, fallbackMessage) {
  const message = getErrorToastMessage(error, fallbackMessage);

  if (error?.data && Object.keys(error.data).length > 0) {
    showJson(element, error.data, true, message);
  } else {
    showMessage(element, error?.message || message, true);
  }

  return message;
}

function updateUploadStatus(status, message, details = {}) {
  const statusClass = status.toLowerCase().replace(/\s+/g, "-");
  uploadStatusBadge.className = `status-badge ${statusClass}`;
  uploadStatusBadge.textContent = status;
  uploadStatusMessage.textContent = message;
  uploadStatusDetails.innerHTML = "";

  for (const [label, value] of Object.entries(details)) {
    if (!value) {
      continue;
    }

    const term = document.createElement("dt");
    term.textContent = label;

    const description = document.createElement("dd");
    description.textContent = value;

    uploadStatusDetails.append(term, description);
  }
}

async function calculateSha256Hex(file) {
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function getResponsePayload(responseData) {
  return responseData?.data && typeof responseData.data === "object" ? responseData.data : responseData;
}

function getUploadUrl(uploadData) {
  return uploadData.upload_url || uploadData.presigned_url || uploadData.presigned_put_url || "";
}

function shouldFallbackToMultipart(error) {
  const message = JSON.stringify(error?.data || error?.message || "").toLowerCase();
  return message.includes("body") && message.includes("file") && message.includes("required");
}

async function parseResponse(response) {
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};

  if (!response.ok) {
    const message = data.detail || `Request failed with status ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data;
}

async function requestJson(path, options = {}) {
  const requestOptions = addAuthorizationHeader(options);
  const response = await fetch(apiUrl(path), requestOptions);
  return parseResponse(response);
}

function addAuthorizationHeader(options = {}) {
  const idToken = window.Auth?.getIdToken();

  if (!idToken) {
    return options;
  }

  return {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${idToken}`,
    },
  };
}

function updateLoginStatus() {
  const idToken = window.Auth?.getIdToken();
  const user = window.Auth?.getUserSummary();

  if (idToken) {
    const label = user?.email || user?.username || "Cognito user";
    loginStatusText.textContent = `Logged in as ${label}. API requests will include an ID token.`;
    loginButton.disabled = true;
    logoutButton.disabled = false;
    if (user?.email && !subscriptionEmailInput.value.trim()) {
      subscriptionEmailInput.value = user.email;
    }
  } else {
    loginStatusText.textContent = "Not logged in. Local API testing is still available.";
    loginButton.disabled = false;
    logoutButton.disabled = true;
  }
}

function parseTagCounts(input) {
  const tags = {};
  const parts = input
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);

  for (const part of parts) {
    const pieces = part.split("=");
    const rawName = pieces[0]?.trim();
    const rawCount = pieces[1]?.trim();

    if (!rawName || pieces.length > 2) {
      throw new Error("Use tags such as bos_taurus or tag=count, for example casuarius_casuarius=1.");
    }

    // Normalise to match the binomial canonical form used by P3's tagging
    // Lambda: lowercase + collapse any whitespace into underscores. So
    // "Bos taurus", "bos_taurus", and "  BOS\tTAURUS " all resolve to the
    // same key the DDB tag index actually stores. Mirrors the Python
    // version in backend/notifications-subscribe/lambda_function.py.
    const tagName = rawName.toLowerCase().split(/\s+/).join("_");

    if (!part.includes("=")) {
      tags[tagName] = 1;
      continue;
    }

    if (!rawCount) {
      throw new Error("Use tags such as bos_taurus or tag=count, for example casuarius_casuarius=1.");
    }

    const count = Number.parseInt(rawCount, 10);
    if (!/^\d+$/.test(rawCount) || !Number.isInteger(count) || count < 1) {
      throw new Error("Use tags such as bos_taurus or tag=count, for example casuarius_casuarius=1.");
    }

    tags[tagName] = count;
  }

  if (Object.keys(tags).length === 0) {
    throw new Error("Enter at least one tag query.");
  }

  return tags;
}

function parseSubscriptionTags(input) {
  const tags = input
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);

  if (tags.length === 0) {
    throw new Error("Enter at least one subscription tag.");
  }

  return tags;
}

function parseDeleteValues(input) {
  return input
    .split(/[\n,]/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function getDeletedCount(data) {
  if (Number.isInteger(data?.deleted_count)) {
    return data.deleted_count;
  }

  if (!Array.isArray(data?.results)) {
    return 0;
  }

  return data.results.filter((item) => ["deleted", "success"].includes(item.status)).length;
}

function isObject(value) {
  return value && typeof value === "object" && !Array.isArray(value);
}

function getDetectedTags(item) {
  if (isObject(item.detected_tags)) {
    return item.detected_tags;
  }

  if (isObject(item.tags)) {
    return item.tags;
  }

  return {};
}

function formatFallbackTagLabel(tagKey) {
  return tagKey
    .split("_")
    .filter(Boolean)
    .map((word) => `${word.charAt(0).toUpperCase()}${word.slice(1).toLowerCase()}`)
    .join(" ");
}

function formatTagLabel(tagKey) {
  return SPECIES_LABELS[tagKey] || MEDIA_TAG_LABELS[tagKey] || formatFallbackTagLabel(tagKey);
}

function formatTagChipText(tagKey, count) {
  return `${formatTagLabel(tagKey)} × ${count}`;
}

function getTagEntries(tags) {
  return Object.entries(tags)
    .map(([tagKey, count]) => [tagKey, Number.isFinite(Number(count)) ? Number(count) : count])
    .filter(([tagKey]) => tagKey);
}

function appendDetectionGroup(container, title, entries, chipClassName) {
  if (entries.length === 0) {
    return;
  }

  const group = document.createElement("div");
  group.className = "detection-group";

  const heading = document.createElement("h4");
  heading.textContent = title;

  const chipList = document.createElement("div");
  chipList.className = "detection-chip-list";

  for (const [tagKey, count] of entries) {
    const chip = document.createElement("span");
    chip.className = `detection-chip ${chipClassName}`;
    chip.textContent = formatTagChipText(tagKey, count);
    chipList.appendChild(chip);
  }

  group.append(heading, chipList);
  container.appendChild(group);
}

function renderDetectedTagGroups(container, tags, emptyMessageText = "No detected tags available.") {
  const entries = getTagEntries(tags);
  container.innerHTML = "";

  if (entries.length === 0) {
    const group = document.createElement("div");
    group.className = "detection-group";

    const heading = document.createElement("h4");
    heading.textContent = "Detected Tags";

    const emptyMessage = document.createElement("p");
    emptyMessage.className = "detection-empty";
    emptyMessage.textContent = emptyMessageText;

    group.append(heading, emptyMessage);
    container.appendChild(group);
    return;
  }

  const speciesEntries = entries.filter(([tagKey]) => !MEDIA_TAG_LABELS[tagKey]);
  const mediaTagEntries = entries.filter(([tagKey]) => MEDIA_TAG_LABELS[tagKey]);

  appendDetectionGroup(container, "Detected Species", speciesEntries, "species-chip");
  appendDetectionGroup(container, "Detected Tags", mediaTagEntries, "media-tag-chip");
}

function renderDetectedTags(container, item) {
  renderDetectedTagGroups(container, getDetectedTags(item));
}

function formatMediaItemCount(count) {
  return `${count} media item${count === 1 ? "" : "s"} found`;
}

function renderQueryFileDetectionResult(data) {
  const detectedTags = data.detected_tags || data.query_tags || {};
  const resultCount = data.count ?? data.results?.length ?? 0;

  queryFileDetectionCard.hidden = false;
  renderDetectedTagGroups(queryFileDetectedTags, detectedTags, "No species detected.");
  queryFileMatchSummary.textContent =
    resultCount > 0 ? formatMediaItemCount(resultCount) : "No matching media found.";
}

async function copyToClipboard(value) {
  if (!value) {
    return;
  }

  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch (error) {
    showToast("Copy failed. Use Technical Details to copy manually.", "error");
    return false;
  }
}

function getObjectKey(item) {
  return item.object_key || item.key || item.s3_key || "";
}

function appendTechnicalDetail(container, label, value) {
  const normalizedValue = Array.isArray(value) ? value.filter(Boolean).join("\n") : value;

  if (!normalizedValue) {
    return;
  }

  const term = document.createElement("dt");
  term.textContent = label;

  const description = document.createElement("dd");
  description.textContent = normalizedValue;

  container.append(term, description);
}

function createResultActionButton(label, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "small-secondary-button";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function renderResultActions(container, item, displayFileUrl) {
  container.innerHTML = "";
  const fileId = item.file_id || "";
  const thumbnailUrl = item.thumbnail_url || "";
  const canOpenFile = isHttpUrl(displayFileUrl) && !isS3Uri(displayFileUrl);

  if (canOpenFile) {
    container.appendChild(
      createResultActionButton("Open File", () => {
        window.open(displayFileUrl, "_blank", "noopener,noreferrer");
      })
    );
  }

  if (fileId) {
    container.appendChild(
      createResultActionButton("Copy File ID", async () => {
        if (await copyToClipboard(fileId)) {
          showToast("File ID copied.", "info");
        }
      })
    );
  }

  if (displayFileUrl) {
    container.appendChild(
      createResultActionButton("Copy File URL", async () => {
        if (await copyToClipboard(displayFileUrl)) {
          showToast("File URL copied.", "info");
        }
      })
    );
  }

  if (thumbnailUrl) {
    container.appendChild(
      createResultActionButton("Copy Thumbnail URL", async () => {
        if (await copyToClipboard(thumbnailUrl)) {
          showToast("Thumbnail URL copied.", "info");
        }
      })
    );
  }
}

function renderTechnicalDetails(container, rawJsonElement, item, displayFileUrl, videoFrameUrls) {
  container.innerHTML = "";
  appendTechnicalDetail(container, "Full File ID", item.file_id);
  appendTechnicalDetail(container, "Full File URL", displayFileUrl);
  appendTechnicalDetail(container, "Thumbnail URL", item.thumbnail_url);
  appendTechnicalDetail(container, "Video Frame URLs", videoFrameUrls);
  appendTechnicalDetail(container, "Video Frame Keys", item.video_frame_keys);
  appendTechnicalDetail(container, "GCP Frame URLs", item.secondary_frame_urls);
  appendTechnicalDetail(container, "Object Key", getObjectKey(item));
  rawJsonElement.textContent = JSON.stringify(item, null, 2);
}

function getOriginalFileUrl(data) {
  const payload = data?.data && typeof data.data === "object" ? data.data : data;
  return payload.file_url || payload.full_url || payload.original_url || payload.url || payload.s3_url || "";
}

function normalizeThumbnailUrl(input) {
  const value = input.trim();

  if (isHttpUrl(value)) {
    return new URL(value).pathname;
  }

  if (value.startsWith("thumbnails/")) {
    return `/${value}`;
  }

  return value;
}

function getThumbnailLookupValue(input, normalizedThumbnailUrl) {
  const value = input.trim();

  if (isHttpUrl(value) || value.startsWith("s3://")) {
    return value;
  }

  const key = normalizedThumbnailUrl.startsWith("/")
    ? normalizedThumbnailUrl.slice(1)
    : normalizedThumbnailUrl;

  if (key.startsWith("thumbnails/")) {
    return `s3://${PRIMARY_MEDIA_BUCKET}/${key}`;
  }

  return normalizedThumbnailUrl;
}

function renderThumbnailQueryOutput(data, message, normalizedThumbnailUrl = "", lookupValue = "") {
  const originalFileUrl = getOriginalFileUrl(data);
  thumbnailQueryOutput.classList.remove("empty", "error");
  thumbnailQueryOutput.classList.add("success");
  thumbnailQueryOutput.innerHTML = "";

  const messageElement = document.createElement("p");
  messageElement.className = "output-message";
  messageElement.textContent = message;
  thumbnailQueryOutput.appendChild(messageElement);

  if (isHttpUrl(originalFileUrl) && !isS3Uri(originalFileUrl)) {
    const actions = document.createElement("div");
    actions.className = "thumbnail-query-actions";
    actions.appendChild(
      createResultActionButton("Open Original File", () => {
        window.open(originalFileUrl, "_blank", "noopener,noreferrer");
      })
    );
    thumbnailQueryOutput.appendChild(actions);
  }

  thumbnailQueryOutput.appendChild(
    createRawResponseDetails({
      normalized_thumbnail_url: normalizedThumbnailUrl,
      lookup_thumbnail_url: lookupValue,
      response: data,
    })
  );
}

function getTagEditResultState(data) {
  const updatedFiles = Array.isArray(data?.updated_files) ? data.updated_files : [];
  const notFound = Array.isArray(data?.not_found) ? data.not_found : [];

  if (notFound.length > 0 && updatedFiles.length === 0) {
    return {
      message: "Tag update completed with warning. No matching file was updated.",
      outputStatus: "warning",
      toastMessage: "No matching file was updated.",
      toastType: "warning",
    };
  }

  if (notFound.length > 0 && updatedFiles.length > 0) {
    return {
      message: "Tag update partially completed. Some files were not found.",
      outputStatus: "warning",
      toastMessage: "Tag update partially completed.",
      toastType: "warning",
    };
  }

  return {
    message: "Tag update completed.",
    outputStatus: "success",
    toastMessage: "Tag update completed.",
    toastType: "success",
  };
}

async function requestThumbnailLookup(normalizedThumbnailUrl, lookupValue) {
  const params = new URLSearchParams();
  params.set("thumbnail_url", normalizedThumbnailUrl);

  try {
    return await requestJson(`/query/thumbnail?${params.toString()}`);
  } catch (error) {
    const message = error?.data?.message || error?.message || "";
    const shouldRetryWithBody =
      error.status === 400 && message.toLowerCase().includes("missing thumbnail_url");

    if (!shouldRetryWithBody) {
      throw error;
    }

    return requestJson("/query/thumbnail", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thumbnail_url: lookupValue }),
    });
  }
}

loginButton.addEventListener("click", async () => {
  loginButton.disabled = true;
  loginStatusText.textContent = "Redirecting to Cognito...";

  try {
    await window.Auth.loginWithCognito();
  } catch (error) {
    loginStatusText.textContent = error.message;
    loginButton.disabled = false;
  }
});

logoutButton.addEventListener("click", () => {
  window.Auth.logout();
  updateLoginStatus();
});

updateLoginStatus();

function fillFollowUpFields(record) {
  if (!record || !record.file_url) {
    return;
  }

  tagFileUrlInput.value = record.file_url;
  deleteFileUrl.value = record.file_url;
}

function buildTagEditRequestBody() {
  const fileUrl = tagFileUrlInput.value.trim();
  const tag = tagNameInput.value.trim();
  const countText = tagCountInput.value.trim();
  const count = parseInt(countText, 10);
  const operation = parseInt(tagOperationSelect.value, 10);

  if (!fileUrl) {
    throw new Error("File URL is required.");
  }

  if (!tag) {
    throw new Error("Tag name is required.");
  }

  if (!countText || !Number.isInteger(count) || count < 1) {
    throw new Error("Count must be a positive number.");
  }

  if (![0, 1].includes(operation)) {
    throw new Error("Operation must be Add or Update, or Remove.");
  }

  return {
    urls: [fileUrl],
    tags: {
      [tag]: count,
    },
    operation,
  };
}

function isImageMedia(item) {
  const mediaTypes = getDisplayMediaTypes(item);
  return mediaTypes.fileType === "image";
}

function isVideoMedia(item) {
  const mediaTypes = getDisplayMediaTypes(item);
  return mediaTypes.fileType === "video" || mediaTypes.mimeType.startsWith("video/");
}

function getDisplayMediaTypes(item) {
  const rawFileType = item.file_type || "unknown";
  const rawMimeType = item.mime_type || "";

  if (rawMimeType) {
    return {
      fileType: rawFileType,
      mimeType: rawMimeType,
    };
  }

  if (rawFileType.startsWith("image/")) {
    return {
      fileType: "image",
      mimeType: rawFileType,
    };
  }

  if (rawFileType.startsWith("video/")) {
    return {
      fileType: "video",
      mimeType: rawFileType,
    };
  }

  return {
    fileType: rawFileType,
    mimeType: "unknown",
  };
}

function getDisplayFileUrl(item) {
  return (
    item.file_url ||
    item.full_url ||
    item.original_url ||
    item.url ||
    item.s3_url ||
    item.object_key ||
    ""
  );
}

function isHttpUrl(value) {
  return typeof value === "string" && /^https?:\/\//i.test(value);
}

function isS3Uri(value) {
  return typeof value === "string" && /^s3:\/\//i.test(value);
}

function toBrowserAssetUrl(value) {
  if (!value) {
    return "";
  }

  if (isHttpUrl(value)) {
    return value;
  }

  if (value.startsWith("/")) {
    return apiUrl(value);
  }

  return value;
}

function getUsableVideoFrameUrls(item) {
  const frameUrls = [
    ...(Array.isArray(item.video_frame_urls) ? item.video_frame_urls : []),
    ...(Array.isArray(item.frame_urls) ? item.frame_urls : []),
    ...(Array.isArray(item.secondary_frame_urls) ? item.secondary_frame_urls : []),
  ];

  return [...new Set(frameUrls)].filter((url) => isHttpUrl(url) && !isS3Uri(url));
}

function getPreviewUrl(item) {
  const thumbnailUrl = item.thumbnail_url || "";

  if (thumbnailUrl) {
    return toBrowserAssetUrl(thumbnailUrl);
  }

  const frameUrls = getUsableVideoFrameUrls(item);
  if (isVideoMedia(item) && frameUrls.length > 0) {
    return frameUrls[0];
  }

  const displayUrl = getDisplayFileUrl(item);
  if (isHttpUrl(displayUrl) && !isS3Uri(displayUrl)) {
    return displayUrl;
  }

  return "";
}

function renderResults(results) {
  resultsGrid.innerHTML = "";

  if (!results || results.length === 0) {
    return;
  }

  const template = document.getElementById("resultCardTemplate");

  for (const item of results) {
    const card = template.content.firstElementChild.cloneNode(true);
    const thumbnailButton = card.querySelector(".thumbnail-button");
    const image = card.querySelector("img");
    const mediaTypes = getDisplayMediaTypes(item);
    const displayFileUrl = getDisplayFileUrl(item);
    const previewUrl = getPreviewUrl(item);
    const hasThumbnail = Boolean(item.thumbnail_url);
    const videoFrameUrls = getUsableVideoFrameUrls(item);

    if (hasThumbnail && previewUrl) {
      image.src = previewUrl;
    } else if (isVideoMedia(item) && videoFrameUrls.length > 0) {
      image.src = previewUrl;

      if (videoFrameUrls.length > 1) {
        const frameStrip = document.createElement("div");
        frameStrip.className = "video-frame-strip";

        videoFrameUrls.forEach((frameUrl, index) => {
          const frameButton = document.createElement("button");
          frameButton.type = "button";
          frameButton.className = `video-frame-button${index === 0 ? " selected" : ""}`;
          frameButton.title = `Preview frame ${index + 1}`;

          const frameImage = document.createElement("img");
          frameImage.src = frameUrl;
          frameImage.alt = `Video frame ${index + 1}`;

          frameButton.appendChild(frameImage);
          frameButton.addEventListener("click", () => {
            image.src = frameUrl;
            frameStrip
              .querySelectorAll(".video-frame-button")
              .forEach((button) => button.classList.remove("selected"));
            frameButton.classList.add("selected");
          });

          frameStrip.appendChild(frameButton);
        });

        thumbnailButton.insertAdjacentElement("afterend", frameStrip);
      }
    } else if (isVideoMedia(item)) {
      image.removeAttribute("src");
      image.alt = "Video frame previews are not available";
      thumbnailButton.classList.add("no-preview", "no-frame-preview");
    } else {
      image.removeAttribute("src");
      image.alt = "No thumbnail preview available";
      thumbnailButton.classList.add("no-preview");
    }

    const frameCount = item.frame_count || videoFrameUrls.length;
    const frameCountRow = card.querySelector('[data-field="frameCountRow"]');
    if (frameCount > 0) {
      frameCountRow.hidden = false;
      card.querySelector('[data-field="frameCount"]').textContent = String(frameCount);
    }
    card.querySelector('[data-field="fileType"]').textContent = mediaTypes.fileType;
    card.querySelector('[data-field="mimeType"]').textContent = mediaTypes.mimeType;
    renderDetectedTags(card.querySelector('[data-field="detectedTags"]'), item);
    renderResultActions(card.querySelector('[data-field="actions"]'), item, displayFileUrl);
    renderTechnicalDetails(
      card.querySelector('[data-field="technicalDetails"]'),
      card.querySelector('[data-field="rawItemJson"]'),
      item,
      displayFileUrl,
      videoFrameUrls
    );

    thumbnailButton.addEventListener("click", async () => {
      const fullUrlField = card.querySelector('[data-field="fullUrl"]');

      if (item.thumbnail_url) {
        fullUrlField.textContent = "Preview image selected. URLs are available in Technical Details.";
        return;
      }

      if (isVideoMedia(item) && videoFrameUrls.length > 0) {
        fullUrlField.textContent = "Video frame preview selected. URLs are available in Technical Details.";
        return;
      }

      if (isVideoMedia(item)) {
        fullUrlField.textContent = "Video frame previews are not available for this result yet.";
        return;
      }

      if (!isHttpUrl(displayFileUrl) || isS3Uri(displayFileUrl)) {
        fullUrlField.textContent = "Thumbnail lookup is not available for this media URL.";
        return;
      }

      fullUrlField.textContent = "Loading full-size image URL...";

      try {
        const params = new URLSearchParams({ thumbnail_url: displayFileUrl });
        const data = await requestJson(`/query/thumbnail?${params.toString()}`);
        fullUrlField.textContent = data.file_url ? "Full-size media URL generated." : "";
      } catch (error) {
        fullUrlField.textContent = "Thumbnail lookup is not available for this result.";
      }
    });

    resultsGrid.appendChild(card);
  }
}

uploadButton.addEventListener("click", async () => {
  const file = uploadFile.files[0];

  if (!file) {
    updateUploadStatus("Failed", "Select an image or video file before uploading.");
    showMessage(uploadOutput, "Select an image or video file first.", true);
    return;
  }

  uploadButton.disabled = true;
  updateUploadStatus("Processing", "Uploading file to the media library.");
  showMessage(uploadOutput, "Uploading file...");

  try {
    const contentType = file.type || "application/octet-stream";
    const checksumSha256 = await calculateSha256Hex(file);

    let result;
    try {
      result = await requestJson("/upload", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: file.name,
          content_type: contentType,
          checksum_sha256: checksumSha256,
        }),
      });
    } catch (error) {
      if (!shouldFallbackToMultipart(error)) {
        throw error;
      }

      const formData = new FormData();
      formData.append("file", file);
      formData.append("checksum_sha256", checksumSha256);

      const uploadResponse = await fetch(
        apiUrl("/upload"),
        addAuthorizationHeader({
          method: "POST",
          body: formData,
        })
      );
      result = await parseResponse(uploadResponse);
    }

    const uploadData = getResponsePayload(result);
    const isDuplicate = result.duplicate === true || uploadData.duplicate === true;

    if (isDuplicate) {
      updateUploadStatus("Duplicate", "This file already exists. Upload skipped.", {
        "Object Key": uploadData.object_key,
        "File URL": uploadData.file_url || uploadData.full_url || uploadData.s3_url,
        "Content Type": uploadData.content_type || uploadData.mime_type || contentType,
      });
      showJson(uploadOutput, result, false, "Duplicate file already exists. Upload skipped.");
      showToast("Duplicate file already exists. Upload skipped.", "warning");
      fillFollowUpFields(uploadData);
      return;
    }

    const uploadUrl = getUploadUrl(uploadData);

    if (uploadUrl) {
      showMessage(uploadOutput, "Uploading file to S3...");

      const putResponse = await fetch(uploadUrl, {
        method: "PUT",
        headers: {
          "Content-Type": contentType,
        },
        body: file,
      });

      if (!putResponse.ok) {
        const error = new Error(`S3 upload failed: HTTP ${putResponse.status}`);
        error.status = putResponse.status;
        throw error;
      }
    }

    updateUploadStatus("Processing", "File uploaded successfully. Detection and indexing are running in the background.", {
      "Object Key": uploadData.object_key,
      "File URL": uploadData.file_url || uploadData.full_url || uploadData.s3_url,
      "Content Type": uploadData.content_type || uploadData.mime_type || contentType,
    });
    showJson(uploadOutput, result, false, "Upload accepted. Processing will continue in the background.");
    showToast("Upload accepted. Processing will continue in the background.", "success");
    fillFollowUpFields(uploadData);
  } catch (error) {
    const errorMessage = showErrorOutput(uploadOutput, error, "Upload failed. Please try again.");
    updateUploadStatus("Failed", errorMessage);
    showToast(errorMessage, "error");
  } finally {
    uploadButton.disabled = false;
  }
});

searchButton.addEventListener("click", async () => {
  searchButton.disabled = true;
  showMessage(queryOutput, "Searching...");
  resultsGrid.innerHTML = "";

  try {
    const tags = parseTagCounts(queryTagsInput.value);
    const data = await requestJson("/query/tags", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(tags),
    });

    const resultCount = data.count ?? data.results?.length ?? 0;
    const queryMessage =
      resultCount > 0
        ? `Query completed. ${resultCount} result(s) found.`
        : "Query completed. No matching results found.";

    showJson(queryOutput, data, false, queryMessage);
    renderResults(data.results);
    showToast(queryMessage, "success");
  } catch (error) {
    const errorMessage = showErrorOutput(queryOutput, error, "Query failed.");
    showToast(errorMessage, "error");
  } finally {
    searchButton.disabled = false;
  }
});

queryFileButton.addEventListener("click", async () => {
  const file = queryFileInput.files[0];

  if (!file) {
    queryFileDetectionCard.hidden = true;
    showMessage(queryFileOutput, "Select a query image or video file first.", true);
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  queryFileButton.disabled = true;
  queryFileDetectionCard.hidden = true;
  showMessage(queryFileOutput, "Searching by file...");
  resultsGrid.innerHTML = "";

  try {
    const data = await requestJson("/query/file", {
      method: "POST",
      body: formData,
    });

    const resultCount = data.count ?? data.results?.length ?? 0;
    const queryMessage =
      resultCount > 0
        ? `File query completed. ${resultCount} result(s) found.`
        : "File query completed. No matching results found.";

    showJson(queryFileOutput, data, false, queryMessage);
    renderQueryFileDetectionResult(data);
    renderResults(data.results);
    showToast(queryMessage, "success");
  } catch (error) {
    const errorMessage = showErrorOutput(queryFileOutput, error, "File query failed.");
    showToast(errorMessage, "error");
  } finally {
    queryFileButton.disabled = false;
  }
});

thumbnailQueryButton.addEventListener("click", async () => {
  const thumbnailUrl = thumbnailQueryInput.value.trim();

  if (!thumbnailUrl) {
    showMessage(thumbnailQueryOutput, "Enter a thumbnail URL first.", true);
    return;
  }

  thumbnailQueryButton.disabled = true;
  showMessage(thumbnailQueryOutput, "Finding original file...");

  const normalizedThumbnailUrl = normalizeThumbnailUrl(thumbnailUrl);
  const lookupValue = getThumbnailLookupValue(thumbnailUrl, normalizedThumbnailUrl);

  try {
    const data = await requestThumbnailLookup(normalizedThumbnailUrl, lookupValue);
    const originalFileUrl = getOriginalFileUrl(data);

    if (!originalFileUrl) {
      renderThumbnailQueryOutput(data, "No matching file found for this thumbnail.", normalizedThumbnailUrl, lookupValue);
      showToast("No matching file found for this thumbnail.", "info");
      return;
    }

    renderThumbnailQueryOutput(data, "Original file found.", normalizedThumbnailUrl, lookupValue);
    showToast("Original file found.", "success");
  } catch (error) {
    if (error.status === 404) {
      renderThumbnailQueryOutput(error.data || {}, "No matching file found for this thumbnail.", normalizedThumbnailUrl, lookupValue);
      showToast("No matching file found for this thumbnail.", "info");
    } else {
      if (error.data && Object.keys(error.data).length > 0) {
        error.data = {
          normalized_thumbnail_url: normalizedThumbnailUrl,
          lookup_thumbnail_url: lookupValue,
          response: error.data,
        };
      }
      const errorMessage = showErrorOutput(thumbnailQueryOutput, error, "Thumbnail query failed.");
      showToast(errorMessage, "error");
    }
  } finally {
    thumbnailQueryButton.disabled = false;
  }
});

editTagsButton.addEventListener("click", async () => {
  editTagsButton.disabled = true;
  showMessage(tagEditOutput, "Updating tags...");

  try {
    const requestBody = buildTagEditRequestBody();
    const data = await requestJson("/tags/edit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });

    const resultState = getTagEditResultState(data);
    showJson(tagEditOutput, data, false, resultState.message, resultState.outputStatus);
    showToast(resultState.toastMessage, resultState.toastType);
  } catch (error) {
    showErrorOutput(tagEditOutput, error, "Tag update failed.");
  } finally {
    editTagsButton.disabled = false;
  }
});

deleteButton.addEventListener("click", async () => {
  const values = parseDeleteValues(deleteFileUrl.value);
  const mode = deleteMode.value;

  if (values.length === 0) {
    showMessage(deleteOutput, "Enter at least one URL or file ID to delete.", true);
    return;
  }

  if (!["urls", "file_ids"].includes(mode)) {
    showMessage(deleteOutput, "Select a valid delete mode.", true);
    return;
  }

  deleteButton.disabled = true;
  showMessage(deleteOutput, "Deleting...");

  try {
    const data = await requestJson("/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [mode]: values }),
    });

    const deletedCount = getDeletedCount(data);
    const deleteMessage =
      deletedCount > 0
        ? `Delete completed. ${deletedCount} file(s) deleted.`
        : "Delete completed. No matching files were deleted.";

    showJson(deleteOutput, data, false, deleteMessage);
    showToast(deleteMessage, deletedCount > 0 ? "success" : "info");
  } catch (error) {
    const errorMessage = showErrorOutput(deleteOutput, error, "Delete failed.");
    showToast(errorMessage, "error");
  } finally {
    deleteButton.disabled = false;
  }
});

subscribeButton.addEventListener("click", async () => {
  const email = subscriptionEmailInput.value.trim();

  if (!email) {
    showMessage(subscriptionOutput, "Email is required.", true);
    return;
  }

  let tags;
  try {
    tags = parseSubscriptionTags(subscriptionTagsInput.value);
  } catch (error) {
    showMessage(subscriptionOutput, error.message, true);
    return;
  }

  subscribeButton.disabled = true;
  showMessage(subscriptionOutput, "Subscribing...");

  try {
    const data = await requestJson("/notifications/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags, email }),
    });

    showJson(subscriptionOutput, data, false, "Subscription created.");
    showToast("Notification subscription created.", "success");
  } catch (error) {
    const errorMessage = showErrorOutput(subscriptionOutput, error, "Subscription failed.");
    showToast(errorMessage, "error");
  } finally {
    subscribeButton.disabled = false;
  }
});
