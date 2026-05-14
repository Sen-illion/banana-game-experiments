const STORAGE_PREFIX = "dn-human-eval";
const DEFAULT_EVALUATOR = "anonymous";

const fallbackDataset = {
  studyTitle: "DN 人类评测",
  mode: "image",
  instructions: ["请通过带 token 的链接进入正式评测。"],
  dimensions: [{ id: "overall", label: "综合评分", help: "总体质量。" }],
  cases: [
    {
      id: "fallback_theme",
      title: "示例主题",
      prompt: ["未加载到正式数据。"],
      context: ["请通过带 token 的邀请链接访问。"],
      storySegments: ["示例段落。"],
      candidates: [{ system: "a", images: [] }, { system: "b", images: [] }],
    },
  ],
};

const state = {
  dataset: fallbackDataset,
  currentIndex: 0,
  evaluatorId: DEFAULT_EVALUATOR,
  ratings: {},
  submittedCases: {},
  warning: "",
  datasetSourceLabel: "当前使用内置示例",
  assignment: null,
  syncStatus: "尚未同步到服务器。",
};

const els = {};

document.addEventListener("DOMContentLoaded", async () => {
  bindElements();
  bindEvents();
  loadEvaluator();
  await loadDataset();
  loadProgress();
  renderAll();
});

function bindElements() {
  Object.assign(els, {
    title: document.querySelector("#study-title"),
    progressLabel: document.querySelector("#progress-label"),
    progressBar: document.querySelector("#progress-bar"),
    evaluatorId: document.querySelector("#evaluator-id"),
    instructionList: document.querySelector("#instruction-list"),
    shareLink: document.querySelector("#share-link"),
    datasetSource: document.querySelector("#dataset-source"),
    copyLink: document.querySelector("#copy-link"),
    datasetFile: document.querySelector("#dataset-file"),
    resetProgress: document.querySelector("#reset-progress"),
    prevCase: document.querySelector("#prev-case"),
    nextCase: document.querySelector("#next-case"),
    sampleIndex: document.querySelector("#sample-index"),
    caseTitle: document.querySelector("#case-title"),
    casePrompt: document.querySelector("#case-prompt"),
    caseContext: document.querySelector("#case-context"),
    storySegments: document.querySelector("#story-segments"),
    warning: document.querySelector("#completion-warning"),
    candidateList: document.querySelector("#candidate-list"),
    candidateTemplate: document.querySelector("#candidate-template"),
    caseStatus: document.querySelector("#case-status"),
    submitCase: document.querySelector("#submit-case"),
    syncStatus: document.querySelector("#sync-status"),
    syncResults: document.querySelector("#sync-results"),
    exportJson: document.querySelector("#export-json"),
    exportCsv: document.querySelector("#export-csv"),
  });
}

function bindEvents() {
  els.evaluatorId.addEventListener("input", () => {
    state.evaluatorId = normalizeEvaluatorId(els.evaluatorId.value);
    localStorage.setItem(`${STORAGE_PREFIX}:evaluator`, els.evaluatorId.value.trim());
    loadProgress();
    renderAll();
  });
  els.copyLink.addEventListener("click", copyCurrentLink);
  els.datasetFile.addEventListener("change", handleDatasetImport);
  els.resetProgress.addEventListener("click", resetProgress);
  els.prevCase.addEventListener("click", () => navigateCase(-1));
  els.nextCase.addEventListener("click", () => navigateCase(1));
  els.submitCase.addEventListener("click", submitCurrentCase);
  els.syncResults.addEventListener("click", () => syncResultsToServer({ manual: true }));
  els.exportJson.addEventListener("click", () => exportResults("json"));
  els.exportCsv.addEventListener("click", () => exportResults("csv"));
}

async function loadDataset() {
  const params = new URLSearchParams(window.location.search);
  const token = params.get("token");
  const mode = params.get("mode");
  if (token) {
    const ok = await loadAssignedTheme(token, mode);
    if (ok) return;
  }

  try {
    const response = await fetch("data/dataset.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.dataset = validateDataset(await response.json());
    state.datasetSourceLabel = "当前数据来自 data/dataset.json";
  } catch (_error) {
    state.dataset = fallbackDataset;
    state.datasetSourceLabel = "当前使用内置示例";
    state.warning = "未能自动加载正式数据。";
  }
}

async function loadAssignedTheme(token, mode) {
  try {
    const query = new URLSearchParams({ token });
    if (mode) query.set("mode", mode);
    const response = await fetch(`/api/session?${query.toString()}`, { cache: "no-store" });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error || `HTTP ${response.status}`);
    }
    const payload = await response.json();
    state.assignment = payload.assignment || null;
    state.dataset = validateDataset(payload.dataset);
    state.datasetSourceLabel = `当前主题：${payload.assignment?.themeTitle || payload.assignment?.themeId || ""}`;
    state.syncStatus = payload.assignment?.submittedAt
      ? `该链接已提交：${payload.assignment.submittedAt}`
      : "提交后会自动同步到服务器。";
    if (payload.assignment?.evaluatorId && !localStorage.getItem(`${STORAGE_PREFIX}:evaluator`)) {
      els.evaluatorId.value = payload.assignment.evaluatorId;
      state.evaluatorId = normalizeEvaluatorId(payload.assignment.evaluatorId);
    }
    return true;
  } catch (error) {
    state.warning = `通过 token 加载失败：${error.message}`;
    return false;
  }
}

function validateDataset(dataset) {
  if (!dataset || !Array.isArray(dataset.cases) || dataset.cases.length === 0) {
    throw new Error("dataset.cases must be a non-empty array");
  }
  if (!Array.isArray(dataset.dimensions) || dataset.dimensions.length === 0) {
    throw new Error("dataset.dimensions must be a non-empty array");
  }
  return {
    studyTitle: dataset.studyTitle || fallbackDataset.studyTitle,
    mode: dataset.mode || "image",
    instructions: Array.isArray(dataset.instructions) ? dataset.instructions : [],
    dimensions: dataset.dimensions,
    cases: dataset.cases.map((item) => ({
      ...item,
      storySegments: normalizeParagraphs(item.storySegments || item.sharedText || item.story || []),
      candidates: (item.candidates || []).map((candidate) => ({
        ...candidate,
        textSegments: normalizeParagraphs(candidate.textSegments || candidate.text || []),
      })),
    })),
  };
}

function loadEvaluator() {
  const stored = localStorage.getItem(`${STORAGE_PREFIX}:evaluator`) || "";
  els.evaluatorId.value = stored;
  state.evaluatorId = normalizeEvaluatorId(stored);
}

function loadProgress() {
  const saved = readProgress();
  state.ratings = saved.ratings || {};
  state.submittedCases = saved.submittedCases || {};
}

function readProgress() {
  try {
    return JSON.parse(localStorage.getItem(storageKey()) || "{}");
  } catch {
    return {};
  }
}

function saveProgress() {
  localStorage.setItem(
    storageKey(),
    JSON.stringify({
      datasetKey: datasetKey(),
      evaluatorId: state.evaluatorId,
      ratings: state.ratings,
      submittedCases: state.submittedCases,
      savedAt: new Date().toISOString(),
    }),
  );
}

function storageKey() {
  return `${STORAGE_PREFIX}:progress:${datasetKey()}:${state.evaluatorId}`;
}

function datasetKey() {
  const ids = state.dataset.cases.map((item) => item.id).join("|");
  return simpleHash(`${state.dataset.studyTitle}|${state.dataset.mode}|${ids}`);
}

function normalizeEvaluatorId(value) {
  const trimmed = String(value || "").trim();
  return trimmed || DEFAULT_EVALUATOR;
}

function renderAll() {
  const cases = state.dataset.cases;
  if (state.currentIndex >= cases.length) state.currentIndex = Math.max(0, cases.length - 1);
  els.title.textContent = state.dataset.studyTitle;
  renderInstructions();
  renderShareInfo();
  renderProgress();
  renderCase();
}

function renderInstructions() {
  els.instructionList.innerHTML = "";
  state.dataset.instructions.forEach((instruction) => {
    const item = document.createElement("p");
    item.className = "instruction-item";
    item.textContent = instruction;
    els.instructionList.appendChild(item);
  });
}

function renderShareInfo() {
  els.shareLink.textContent = resolveShareUrl();
  els.datasetSource.textContent = state.datasetSourceLabel;
}

function renderProgress() {
  const total = state.dataset.cases.length;
  const completed = state.dataset.cases.filter((item) => state.submittedCases[item.id]).length;
  const percent = total ? Math.round((completed / total) * 100) : 0;
  els.progressLabel.textContent = `${completed} / ${total} 已完成`;
  els.progressBar.style.width = `${percent}%`;
}

function renderCase() {
  const currentCase = getCurrentCase();
  const total = state.dataset.cases.length;
  const caseComplete = isCaseComplete(currentCase);
  const caseSubmitted = Boolean(state.submittedCases[currentCase.id]);

  els.sampleIndex.textContent = `主题 ${state.currentIndex + 1} / ${total}`;
  els.caseTitle.textContent = currentCase.title || currentCase.id;
  els.casePrompt.textContent = formatDisplayText(currentCase.prompt, "未提供主题说明");
  els.caseContext.textContent = formatDisplayText(currentCase.context, "未提供上下文");
  els.prevCase.disabled = state.currentIndex === 0;
  els.nextCase.disabled = state.currentIndex >= total - 1;
  els.submitCase.disabled = !caseComplete;
  els.caseStatus.textContent = caseSubmitted ? "当前主题已提交" : caseComplete ? "当前主题可提交" : "当前主题未完成";
  els.syncStatus.textContent = state.syncStatus;

  if (state.warning) {
    els.warning.hidden = false;
    els.warning.textContent = state.warning;
  } else {
    els.warning.hidden = true;
    els.warning.textContent = "";
  }

  renderStorySegments(currentCase.storySegments || []);
  renderCandidates(currentCase);
}

function renderStorySegments(segments) {
  els.storySegments.innerHTML = "";
  segments.forEach((segment, index) => {
    const block = document.createElement("article");
    block.className = "story-segment";
    block.innerHTML = `<p class="story-segment-title">段落 ${index + 1}</p><p class="rich-copy">${escapeHtml(segment)}</p>`;
    els.storySegments.appendChild(block);
  });
}

function renderCandidates(currentCase) {
  els.candidateList.innerHTML = "";
  const isTextMode = state.dataset.mode === "text";
  getAnonymousCandidates(currentCase).forEach((candidate) => {
    const fragment = els.candidateTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".candidate-card");
    const label = fragment.querySelector(".candidate-label");
    const completion = fragment.querySelector(".candidate-completion");
    const copy = fragment.querySelector(".candidate-copy");
    const strip = fragment.querySelector(".image-strip");
    const ratingList = fragment.querySelector(".rating-list");
    const note = fragment.querySelector("textarea");
    const complete = isCandidateComplete(currentCase.id, candidate.label);

    card.dataset.label = candidate.label;
    card.classList.toggle("is-complete", complete);
    label.textContent = `方案 ${candidate.label}`;
    completion.textContent = complete ? "已完成" : "待评分";

    if (copy) {
      copy.textContent = isTextMode ? "请仅基于该方案文本内容评分。" : "请仅基于该方案图片内容评分。";
    }
    renderSegmentPairs(strip, currentCase.storySegments || [], candidate, state.dataset.mode);
    renderRatings(ratingList, currentCase.id, candidate.label);

    note.value = getCandidateState(currentCase.id, candidate.label).note || "";
    note.addEventListener("input", () => {
      const candidateState = getCandidateState(currentCase.id, candidate.label);
      candidateState.note = note.value;
      state.submittedCases[currentCase.id] = false;
      saveProgress();
      renderProgress();
    });
    els.candidateList.appendChild(fragment);
  });
}

function renderSegmentPairs(container, sharedSegments, candidate, mode) {
  container.innerHTML = "";
  const isTextMode = mode === "text";
  container.classList.toggle("text-mode", isTextMode);
  container.classList.toggle("image-mode", !isTextMode);
  const candidateTexts = normalizeParagraphs(candidate.textSegments || []);
  const images = Array.isArray(candidate.images) ? candidate.images : [];
  const segmentCount = isTextMode
    ? candidateTexts.length
    : Math.max(sharedSegments.length, images.length);

  if (segmentCount === 0) {
    const empty = document.createElement("p");
    empty.className = "image-caption";
    empty.textContent = "无可展示内容。";
    container.appendChild(empty);
    return;
  }

  for (let i = 0; i < segmentCount; i += 1) {
    const frame = document.createElement("figure");
    frame.className = "image-frame";

    const caption = document.createElement("figcaption");
    caption.className = "image-caption";
    caption.textContent = `段落 ${i + 1}`;
    frame.appendChild(caption);

    if (isTextMode) {
      const candidateText = candidateTexts[i];
      if (candidateText) {
        const p = document.createElement("p");
        p.className = "rich-copy";
        p.textContent = candidateText;
        frame.appendChild(p);
      }
    } else {
      const src = images[i];
      if (src) {
        const img = document.createElement("img");
        img.src = src;
        img.alt = `候选方案图像 ${i + 1}`;
        img.loading = "lazy";
        frame.appendChild(img);
      }
    }

    container.appendChild(frame);
  }
}

function renderRatings(container, caseId, label) {
  container.innerHTML = "";
  const candidateState = getCandidateState(caseId, label);
  const missing = getMissingDimensions(caseId, label);

  state.dataset.dimensions.forEach((dimension) => {
    const row = document.createElement("div");
    row.className = "rating-row";
    row.classList.toggle("is-missing", missing.includes(dimension.id));
    const heading = document.createElement("div");
    heading.className = "rating-label";
    heading.innerHTML = `<span>${escapeHtml(dimension.label)}</span><span>${candidateState.scores?.[dimension.id] || "-"} / 10</span>`;
    const help = document.createElement("div");
    help.className = "rating-help";
    help.textContent = dimension.help || "";
    const options = document.createElement("div");
    options.className = "rating-options";

    for (let score = 1; score <= 10; score += 1) {
      const button = document.createElement("button");
      button.className = "rating-option";
      button.type = "button";
      button.textContent = score;
      button.classList.toggle("is-selected", candidateState.scores?.[dimension.id] === score);
      button.setAttribute("aria-pressed", String(candidateState.scores?.[dimension.id] === score));
      button.addEventListener("click", () => setScore(caseId, label, dimension.id, score));
      options.appendChild(button);
    }
    row.append(heading, help, options);
    container.appendChild(row);
  });
}

function setScore(caseId, label, dimensionId, score) {
  const candidateState = getCandidateState(caseId, label);
  candidateState.scores = candidateState.scores || {};
  candidateState.scores[dimensionId] = score;
  state.submittedCases[caseId] = false;
  state.warning = "";
  saveProgress();
  renderProgress();
  renderCase();
}

function getCurrentCase() {
  return state.dataset.cases[state.currentIndex];
}

function getAnonymousCandidates(currentCase) {
  const candidates = Array.isArray(currentCase.candidates) ? [...currentCase.candidates] : [];
  const sorted = candidates
    .map((candidate, index) => ({ ...candidate, originalIndex: index }))
    .sort((a, b) => {
      const aHash = simpleHash(`${state.evaluatorId}|${currentCase.id}|${a.system}|${a.originalIndex}`);
      const bHash = simpleHash(`${state.evaluatorId}|${currentCase.id}|${b.system}|${b.originalIndex}`);
      return aHash.localeCompare(bHash);
    });
  return sorted.map((candidate, index) => ({ ...candidate, label: String.fromCharCode(65 + index) }));
}

function getCandidateState(caseId, label) {
  state.ratings[caseId] = state.ratings[caseId] || {};
  state.ratings[caseId][label] = state.ratings[caseId][label] || { scores: {}, note: "" };
  return state.ratings[caseId][label];
}

function getMissingDimensions(caseId, label) {
  const candidateState = getCandidateState(caseId, label);
  return state.dataset.dimensions.map((d) => d.id).filter((id) => !Number.isInteger(candidateState.scores?.[id]));
}

function isCandidateComplete(caseId, label) {
  return getMissingDimensions(caseId, label).length === 0;
}

function isCaseComplete(currentCase) {
  return getAnonymousCandidates(currentCase).every((candidate) => isCandidateComplete(currentCase.id, candidate.label));
}

function submitCurrentCase() {
  const currentCase = getCurrentCase();
  const missingLabels = getAnonymousCandidates(currentCase)
    .filter((candidate) => !isCandidateComplete(currentCase.id, candidate.label))
    .map((candidate) => `方案 ${candidate.label}`);
  if (missingLabels.length) {
    state.warning = `请先完成 ${missingLabels.join("、")} 的所有评分。`;
    renderCase();
    return;
  }

  state.submittedCases[currentCase.id] = new Date().toISOString();
  state.warning = "";
  saveProgress();
  renderAll();
  if (state.assignment?.token) {
    syncResultsToServer({ manual: false });
  } else {
    state.syncStatus = "当前未绑定 token，结果仅保存在本地。";
    renderCase();
  }
}

function navigateCase(delta) {
  const nextIndex = state.currentIndex + delta;
  if (nextIndex < 0 || nextIndex >= state.dataset.cases.length) return;
  state.currentIndex = nextIndex;
  state.warning = "";
  renderCase();
}

async function handleDatasetImport(event) {
  const [file] = event.target.files;
  if (!file) return;
  try {
    state.dataset = validateDataset(JSON.parse(String(await file.text()).replace(/^\uFEFF/, "")));
    state.currentIndex = 0;
    state.assignment = null;
    state.datasetSourceLabel = `当前数据来自本地文件：${file.name}`;
    state.syncStatus = "手动导入模式不自动回传。";
    state.warning = `已导入 ${file.name}`;
    loadProgress();
    renderAll();
  } catch (error) {
    state.warning = `导入失败：${error.message}`;
    renderCase();
  } finally {
    event.target.value = "";
  }
}

function resetProgress() {
  if (!window.confirm("确定清空当前评测进度吗？")) return;
  localStorage.removeItem(storageKey());
  state.ratings = {};
  state.submittedCases = {};
  state.warning = "本地进度已清空。";
  renderAll();
}

async function syncResultsToServer({ manual }) {
  if (!state.assignment?.token) return;
  try {
    const response = await fetch("/api/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token: state.assignment.token,
        evaluatorId: state.evaluatorId,
        assignment: state.assignment,
        payload: buildExportPayload(),
      }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    state.syncStatus = manual ? `已重新同步：${result.savedAt}` : `提交成功：${result.savedAt}`;
    renderCase();
  } catch (error) {
    state.syncStatus = `同步失败：${error.message}`;
    renderCase();
  }
}

function exportResults(format) {
  const payload = buildExportPayload();
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  if (format === "json") {
    downloadFile(`human_eval_results_${timestamp}.json`, JSON.stringify(payload, null, 2), "application/json");
    return;
  }
  downloadFile(`human_eval_results_${timestamp}.csv`, toCsv(payload), "text/csv;charset=utf-8");
}

function buildExportPayload() {
  const exportedAt = new Date().toISOString();
  const cases = state.dataset.cases.map((currentCase) => {
    const anonymousCandidates = getAnonymousCandidates(currentCase);
    return {
      caseId: currentCase.id,
      title: currentCase.title || "",
      submittedAt: state.submittedCases[currentCase.id] || null,
      storySegments: currentCase.storySegments || [],
      mapping: Object.fromEntries(anonymousCandidates.map((c) => [c.label, c.system || "unknown"])),
      ratings: anonymousCandidates.map((candidate) => {
        const candidateState = getCandidateState(currentCase.id, candidate.label);
        return {
          anonymousLabel: candidate.label,
          system: candidate.system || "unknown",
          imageCount: Array.isArray(candidate.images) ? candidate.images.length : 0,
          textCount: Array.isArray(candidate.textSegments) ? candidate.textSegments.length : 0,
          scores: candidateState.scores || {},
          note: candidateState.note || "",
          complete: isCandidateComplete(currentCase.id, candidate.label),
        };
      }),
    };
  });
  return {
    studyTitle: state.dataset.studyTitle,
    mode: state.dataset.mode,
    evaluatorId: state.evaluatorId,
    exportedAt,
    assignment: state.assignment,
    dimensions: state.dataset.dimensions,
    cases,
  };
}

function toCsv(payload) {
  const columns = [
    "studyTitle",
    "mode",
    "evaluatorId",
    "themeId",
    "exportedAt",
    "caseId",
    "caseTitle",
    "submittedAt",
    "anonymousLabel",
    "system",
    "imageCount",
    "textCount",
    "dimensionId",
    "dimensionLabel",
    "score",
    "note",
    "complete",
  ];
  const rows = [columns];
  payload.cases.forEach((caseResult) => {
    caseResult.ratings.forEach((rating) => {
      payload.dimensions.forEach((dimension) => {
        rows.push([
          payload.studyTitle,
          payload.mode || "",
          payload.evaluatorId,
          payload.assignment?.themeId || "",
          payload.exportedAt,
          caseResult.caseId,
          caseResult.title,
          caseResult.submittedAt || "",
          rating.anonymousLabel,
          rating.system,
          rating.imageCount,
          rating.textCount,
          dimension.id,
          dimension.label,
          rating.scores?.[dimension.id] || "",
          rating.note,
          rating.complete,
        ]);
      });
    });
  });
  return rows.map((row) => row.map(csvEscape).join(",")).join("\n");
}

function csvEscape(value) {
  const v = String(value ?? "");
  return /[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

function downloadFile(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function formatDisplayText(value, fallback) {
  const parts = normalizeParagraphs(value);
  return parts.length ? parts.join("\n\n") : fallback;
}

function normalizeParagraphs(value) {
  if (Array.isArray(value)) return value.map((item) => String(item || "").trim()).filter(Boolean);
  const text = String(value || "").trim();
  if (!text) return [];
  if (text.includes("\n\n")) return text.split(/\n{2,}/).map((item) => item.trim()).filter(Boolean);
  return [text];
}

function resolveShareUrl() {
  return new URL(window.location.href).toString();
}

async function copyCurrentLink() {
  const url = resolveShareUrl();
  try {
    await navigator.clipboard.writeText(url);
    state.warning = "当前链接已复制。";
  } catch {
    state.warning = `复制失败，请手动复制：${url}`;
  }
  renderCase();
}

function simpleHash(input) {
  let hash = 2166136261;
  const text = String(input);
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function escapeHtml(value) {
  const span = document.createElement("span");
  span.textContent = value;
  return span.innerHTML;
}
