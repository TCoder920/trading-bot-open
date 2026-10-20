import { useState } from "react";

export default function Tooltip({ text }) {
  const [show, setShow] = useState(false);
  if (!text) return null;
  return (
    <span
      className="tooltip-wrap"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      <span className="tooltip-icon">ⓘ</span>
      {show && <span className="tooltip-bubble">{text}</span>}
    </span>
  );
}
