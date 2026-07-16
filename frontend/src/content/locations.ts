export interface Location {
  name: string;
  addressLines: string[];
  mapsEmbedUrl: string;
}

export const locations: Location[] = [
  {
    name: "Watersportcentrum 'Het Bastion'",
    addressLines: ["Oudedijk 3", "6663 KZ Nijmegen"],
    mapsEmbedUrl:
      "https://maps.google.com/maps?q=Watersportcentrum%20%22Het%20Bastion%22%2C%20Oudedijk%2C%20Nijmegen&t=m&z=15&output=embed&iwloc=near",
  },
  {
    name: "'Villa van Schaeck'",
    addressLines: ["Van Schaeck Mathonsingel 10", "6512 AP Nijmegen"],
    mapsEmbedUrl:
      "https://maps.google.com/maps?q=Villa%20van%20Schaeck%2C%20Van%20Schaeck%20Mathonsingel%2C%20Nijmegen&t=m&z=15&output=embed&iwloc=near",
  },
];
