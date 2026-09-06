/* Minimal client for the Robot Dispatch demo call. */

const INPUT_SAMPLE_RATE = 16000;
const OUTPUT_SAMPLE_RATE = 24000;

const els = {
  answer: document.getElementById("answer"),
  hangup: document.getElementById("hangup"),
  status: document.getElementById("status"),
  hint: document.getElementById("hint"),
  transcriptPanel: document.getElementById("transcript-panel"),
  transcript: document.getElementById("transcript"),
  resultPanel: document.getElementById("result-panel"),
  result: document.getElementById("result"),
  error: document.getElementById("error"),
};

let socket = null;
let micStream = null;
let micContext = null;
let micNode = null;
let playbackContext = null;
let playbackCursor = 0;
let activeSources = [];
let pendingResult = null;
let ended = false;
let finished = false;
let lastRole = null;

function setStatus(text, live) {
  els.status.textContent = text;
  els.status.classList.toggle("live", Boolean(live));
}

function showError(message) {
  els.error.textContent = message;
  els.error.hidden = false;
}

function appendTranscript(role, text) {
  els.transcriptPanel.hidden = false;
  const label = role === "agent" ? "Agent" : "You";
  let line = els.transcript.lastElementChild;
  if (lastRole !== role || !line) {
    line = document.createElement("li");
    line.innerHTML = `<span>${label}</span>`;
    line.appendChild(document.createTextNode(""));
    els.transcript.appendChild(line);
    lastRole = role;
  }
  line.lastChild.textContent += text;
}

function base64ToArrayBuffer(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function playChunk(base64) {
  if (!playbackContext || finished) {
    return;
  }
  const pcm = new Int16Array(base64ToArrayBuffer(base64));
  if (!pcm.length) {
    return;
  }
  const buffer = playbackContext.createBuffer(
    1,
    pcm.length,
    OUTPUT_SAMPLE_RATE
  );
  const channel = buffer.getChannelData(0);
  for (let i = 0; i < pcm.length; i += 1) {
    channel[i] = pcm[i] / 0x8000;
  }
  const source = playbackContext.createBufferSource();
  source.buffer = buffer;
  source.connect(playbackContext.destination);
  const startAt = Math.max(playbackContext.currentTime, playbackCursor);
  source.start(startAt);
  playbackCursor = startAt + buffer.duration;
  activeSources.push(source);
  source.onended = () => {
    activeSources = activeSources.filter((item) => item !== source);
    if (ended && activeSources.length === 0) {
      finishCall();
    }
  };
}

function stopPlayback() {
  activeSources.forEach((source) => {
    try {
      source.stop();
    } catch (err) {
      /* already stopped */
    }
  });
  activeSources = [];
  playbackCursor = 0;
}

function closePlayback() {
  stopPlayback();
  if (playbackContext) {
    playbackContext.close();
    playbackContext = null;
  }
}

async function startMicrophone() {
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
    },
  });
  micContext = new AudioContext({ sampleRate: INPUT_SAMPLE_RATE });
  await micContext.audioWorklet.addModule("/static/pcm-recorder.js");
  const source = micContext.createMediaStreamSource(micStream);
  micNode = new AudioWorkletNode(micContext, "pcm-recorder");
  micNode.port.onmessage = (event) => {
    if (socket && socket.readyState === WebSocket.OPEN && !ended) {
      socket.send(
        JSON.stringify({
          type: "audio",
          data: arrayBufferToBase64(event.data),
        })
      );
    }
  };
  source.connect(micNode);
}

function stopMicrophone() {
  if (micNode) {
    micNode.port.onmessage = null;
    micNode.disconnect();
    micNode = null;
  }
  if (micStream) {
    micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
  }
  if (micContext) {
    micContext.close();
    micContext = null;
  }
}

function finishCall() {
  if (finished) {
    return;
  }
  finished = true;
  stopMicrophone();
  closePlayback();
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.close();
  }
  els.hangup.hidden = true;
  els.answer.hidden = false;
  els.answer.disabled = false;
  els.answer.textContent = "Start another demo call";
  setStatus("Call ended", false);
  els.hint.textContent = pendingResult
    ? "The agent recorded your answer below."
    : "No answer was recorded during this call.";
  if (pendingResult) {
    els.resultPanel.hidden = false;
    els.result.textContent = JSON.stringify(pendingResult, null, 2);
  }
}

function handleMessage(event) {
  const message = JSON.parse(event.data);
  switch (message.type) {
    case "ready":
      setStatus("Connected — the agent is speaking", true);
      break;
    case "audio":
      playChunk(message.data);
      break;
    case "transcript":
      appendTranscript(message.role, message.text);
      break;
    case "interrupted":
      stopPlayback();
      if (ended) {
        finishCall();
      }
      break;
    case "result":
      pendingResult = message.data;
      break;
    case "call_ended":
      ended = true;
      setStatus("The agent is hanging up…", true);
      if (activeSources.length === 0) {
        finishCall();
      }
      break;
    case "error":
      showError(message.message);
      ended = true;
      finishCall();
      break;
    default:
      break;
  }
}

async function answerCall() {
  els.answer.disabled = true;
  els.answer.hidden = true;
  els.error.hidden = true;
  els.resultPanel.hidden = true;
  els.transcript.innerHTML = "";
  els.transcriptPanel.hidden = true;
  pendingResult = null;
  ended = false;
  finished = false;
  lastRole = null;
  setStatus("Connecting…", false);

  try {
    playbackContext = new AudioContext({ sampleRate: OUTPUT_SAMPLE_RATE });
    await playbackContext.resume();
    await startMicrophone();
  } catch (err) {
    showError(`Microphone access is required: ${err.message}`);
    els.answer.hidden = false;
    els.answer.disabled = false;
    setStatus("Incoming demo call", false);
    return;
  }

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${window.location.host}/ws/call`);
  socket.onmessage = handleMessage;
  socket.onerror = () => showError("Connection to the server failed.");
  socket.onclose = () => {
    if (!ended) {
      ended = true;
      finishCall();
    }
  };

  els.hangup.hidden = false;
  els.hint.textContent = "Speak into your microphone to answer the agent.";
}

function hangUp() {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "hangup" }));
  }
  ended = true;
  finishCall();
}

els.answer.addEventListener("click", answerCall);
els.hangup.addEventListener("click", hangUp);
