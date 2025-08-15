import {
    MdDelete
} from 'react-icons/md';

interface Props {
    title?: string;
    header: string[];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    body: any[][];
    actions?: boolean;
    button?: string;
    onButton?: () => void;
    onDelete?: (index: number) => void;
    link?: string;
    indexLink?: number;
}

const Info = ({title, header, body, actions, button, onButton, onDelete, link, indexLink}: Props) => {
  return (
    <div className="bg-[var(--bgSoft)] p-4 rounded-lg shadow-xl">
        <div className="flex justify-between mb-4 items-center">
            <h2 className="mb-1 font-semibold text-[var(--textSoft)] text-xl mb-2">
                {title}
            </h2>
            {button &&
                <button
                    className="bg-[#2e374a] text-white p-2 rounded-lg hover:bg-[#3e4f6c] cursor-pointer"
                    onClick={onButton}
                >
                    {button}
                </button>
            }
        </div>
        <table className="w-full">
            <thead>
                <tr>
                    {header?.map((item, index) => (
                        <th
                            key={index}
                            className={"p-2"}
                        >
                            {item}
                        </th>
                    ))}
                </tr>
            </thead>
            <tbody>
                {body?.map((item, index) => (
                    <tr key={index}>
                        {item.map((data, i) => (
                            <td 
                                key={i} 
                                className={`bg-[var(--bg)] border-b-3 border-b-[var(--bgSoft)] h-14 p-2
                                    ${i === 0 && 'rounded-s-3xl'}
                                    ${i === item.length - 1 && !actions && 'rounded-e-3xl'}
                                    ${!(i === 0 && title === 'Recent Tasks') && 'text-center'}
                                `}
                            >
                                <a
                                    {...(link && i === indexLink) && {href: link.concat(body[index][5]), target: "_blank"}}
                                    className={`py-2 px-4 text-base text-white rounded-xl
                                        ${(data === 'Online' || data === 'Completed') && 'bg-[#2ecc71]'}
                                        ${(data === 'Idle' || data === 'Running') && 'bg-[#f1c40f]'}
                                        ${(data === 'Busy' || data === 'Processing') && 'bg-[#e74c3c]'}
                                        ${data === 'Pending' && 'bg-[grey]'}`
                                    }
                                >
                                    {data?.length > 20 ? `${data.slice(0, 60)}...` : data}{body[index][5]}
                                </a>
                            </td>
                        ))}
                        {actions &&
                            <td
                                key={item.length}
                                className="bg-[var(--bg)] border-b-3 border-b-[var(--bgSoft)] h-14 p-2 rounded-e-3xl"
                            >
                                <MdDelete
                                    className="text-[#e74c3c] cursor-pointer mx-auto"
                                    onClick={() => {if(onDelete) onDelete(index)}}
                                />
                            </td>
                        }
                    </tr>
                ))}
            </tbody>
        </table>
    </div>
  );
};

export default Info;