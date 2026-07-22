// static/js/wall_preview.js

function qs(sel, root = document) { return root.querySelector(sel); }

document.addEventListener("DOMContentLoaded", () => {
  const canvas = qs("#wallCanvas");
  const fileInput = qs("#wallFile");
  const resetBtn = qs("#resetWallBtn");

  if (!canvas || !fileInput || !resetBtn) return;

  const ctx = canvas.getContext("2d");

  const wallImg = new Image();
  const posterImg = new Image();

  // Poster source: product poster preview
  const posterDom = qs("#posterImg");
  posterImg.src = posterDom ? posterDom.src : "";

  // State
  let wallLoaded = false;
  let posterLoaded = false;

  let posterX = canvas.width * 0.58;
  let posterY = canvas.height * 0.55;
  let posterScale = 0.45;

  let dragging = false;
  let dragOffsetX = 0;
  let dragOffsetY = 0;

  function clamp(val, min, max) {
    return Math.max(min, Math.min(max, val));
  }

  function getPosterSize() {
    // keep poster ratio
    const w = posterImg.width || 600;
    const h = posterImg.height || 800;
    const baseW = 260;
    const ratio = h / w;
    return {
      w: baseW * posterScale,
      h: baseW * ratio * posterScale
    };
  }

  function drawCheckerBackground() {
    // fallback "wall" look if no wall photo uploaded
    ctx.fillStyle = "#0f1318";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // subtle grid
    ctx.globalAlpha = 0.12;
    ctx.strokeStyle = "#ffffff";
    for (let x = 0; x < canvas.width; x += 40) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, canvas.height);
      ctx.stroke();
    }
    for (let y = 0; y < canvas.height; y += 40) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(canvas.width, y);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (wallLoaded) {
      // cover-fit wall image
      const scale = Math.max(canvas.width / wallImg.width, canvas.height / wallImg.height);
      const w = wallImg.width * scale;
      const h = wallImg.height * scale;
      const x = (canvas.width - w) / 2;
      const y = (canvas.height - h) / 2;
      ctx.drawImage(wallImg, x, y, w, h);
    } else {
      drawCheckerBackground();
      ctx.fillStyle = "rgba(233,238,246,0.65)";
      ctx.font = "14px system-ui, -apple-system, Segoe UI, Roboto";
      ctx.fillText("Upload a wall photo to preview your frame", 18, 28);
    }

    if (!posterLoaded) {
      ctx.fillStyle = "rgba(233,238,246,0.75)";
      ctx.font = "14px system-ui, -apple-system, Segoe UI, Roboto";
      ctx.fillText("Poster preview loading…", 18, canvas.height - 18);
      return;
    }

    const ps = getPosterSize();

    // clamp poster center so it doesn’t fully fly away
    posterX = clamp(posterX, ps.w / 2, canvas.width - ps.w / 2);
    posterY = clamp(posterY, ps.h / 2, canvas.height - ps.h / 2);

    const drawX = posterX - ps.w / 2;
    const drawY = posterY - ps.h / 2;

    // shadow behind frame
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.55)";
    ctx.shadowBlur = 18;
    ctx.shadowOffsetX = 0;
    ctx.shadowOffsetY = 10;

    // frame border
    ctx.fillStyle = "rgba(10,12,15,0.85)";
    ctx.fillRect(drawX - 10, drawY - 10, ps.w + 20, ps.h + 20);
    ctx.restore();

    // inner matte
    ctx.fillStyle = "rgba(0,0,0,0.35)";
    ctx.fillRect(drawX - 4, drawY - 4, ps.w + 8, ps.h + 8);

    // poster image itself
    ctx.drawImage(posterImg, drawX, drawY, ps.w, ps.h);

    // hint
    ctx.fillStyle = "rgba(0,0,0,0.45)";
    ctx.fillRect(12, canvas.height - 44, 300, 30);
    ctx.fillStyle = "rgba(233,238,246,0.85)";
    ctx.font = "12px system-ui, -apple-system, Segoe UI, Roboto";
    ctx.fillText("Drag to move • Scroll to zoom • Reset to start", 22, canvas.height - 24);
  }

  // Load poster (from #posterImg)
  posterImg.onload = () => {
    posterLoaded = true;
    draw();
  };
  posterImg.onerror = () => {
    // fallback: still allow wall preview, but show message
    posterLoaded = false;
    draw();
  };

  // Upload wall photo
  fileInput.addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = () => {
      wallImg.onload = () => {
        wallLoaded = true;
        draw();
      };
      wallImg.src = reader.result;
    };
    reader.readAsDataURL(file);
  });

  // Drag poster
  canvas.addEventListener("pointerdown", (e) => {
    if (!posterLoaded) return;
    dragging = true;
    canvas.setPointerCapture(e.pointerId);

    dragOffsetX = e.offsetX - posterX;
    dragOffsetY = e.offsetY - posterY;
  });

  canvas.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    posterX = e.offsetX - dragOffsetX;
    posterY = e.offsetY - dragOffsetY;
    draw();
  });

  canvas.addEventListener("pointerup", () => {
    dragging = false;
  });

  canvas.addEventListener("pointercancel", () => {
    dragging = false;
  });

  // Zoom via mouse wheel
  canvas.addEventListener("wheel", (e) => {
    if (!posterLoaded) return;
    e.preventDefault();
    const delta = Math.sign(e.deltaY);
    const step = 0.05;

    if (delta > 0) posterScale -= step;
    else posterScale += step;

    posterScale = clamp(posterScale, 0.20, 1.20);
    draw();
  }, { passive: false });

  // Reset
  resetBtn.addEventListener("click", () => {
    wallLoaded = false;
    fileInput.value = "";

    posterX = canvas.width * 0.58;
    posterY = canvas.height * 0.55;
    posterScale = 0.45;

    draw();
  });

  // If poster changes dynamically on page, you can call this to refresh:
  // posterImg.src = qs("#posterImg").src;

  // Initial draw
  draw();
});
