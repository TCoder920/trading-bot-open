export default function PageShell({ title, description, actions, children }) {
  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">{title}</h1>
          {description && (
            <p className="page-description">{description}</p>
          )}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </div>
      {children}
    </div>
  );
}
