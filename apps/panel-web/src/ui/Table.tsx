import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: string;
  num?: boolean;
  render: (row: T) => ReactNode;
}

export function Table<T>({ columns, rows, rowKey, toolbar, selected }: { columns: Column<T>[]; rows: T[]; rowKey: (row: T) => string; toolbar?: ReactNode; selected?: (row: T) => boolean }) {
  return (
    <div className="ns-table-wrap">
      {toolbar ? <div className="ns-table-toolbar">{toolbar}</div> : null}
      <table className="ns-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={c.num ? "num" : undefined} scope="col">
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={rowKey(r)} className={selected?.(r) ? "is-selected" : undefined}>
              {columns.map((c) => (
                <td key={c.key} className={c.num ? "num" : undefined}>
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
