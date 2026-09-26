import React, {type ComponentProps, useEffect, useRef, useState} from 'react';
import MDXComponents from '@theme-original/MDXComponents';
import CodeExample from '../../components/CodeExample';

function Table(props: ComponentProps<'table'>) {
  const ref = useRef<HTMLTableElement>(null);
  const [scrollable, setScrollable] = useState(false);
  useEffect(() => {
    const table = ref.current;
    if (!table) return;
    const measure = () => setScrollable(table.scrollWidth > table.clientWidth + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(table);
    return () => observer.disconnect();
  }, []);
  return <table {...props} ref={ref} tabIndex={props.tabIndex ?? (scrollable ? 0 : undefined)} />;
}

export default {...MDXComponents, table: Table, CodeExample};
