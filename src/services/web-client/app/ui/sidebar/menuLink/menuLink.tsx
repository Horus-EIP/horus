import Link from 'next/link';
import { JSX } from 'react/jsx-runtime';

type props = {
    item: {
        title: string;
        link: string;
        icon: JSX.Element;
        path?: string;
    }
}

const MenuLink = ({item} : props) => {
    
    return (
        <Link
            href={item.link}
            className="p-5 flex items-center gap-3 my-2 rounded-lg hover:bg-[#2e374a] hover:rounded-lg"
        >
            {item.icon}
            {item.title}
        </Link>
    )
}

export default MenuLink;
